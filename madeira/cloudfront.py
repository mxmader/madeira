from datetime import datetime
import madeira
import boto3

import time


class CloudFront(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else madeira.get_logger()
        self._session = boto3.session.Session(profile_name=profile_name, region_name=region)
        self.cloudfront_client = self._session.client('cloudfront')

    def get_distribution_by_hostname(self, hostname):
        for distro in self.cloudfront_client.list_distributions()['DistributionList']['Items']:
            if distro['Comment'] == f"Distribution for {hostname}":
                return distro

        return None

    def invalidate_cache(self, distro_id, items='/*'):
        self._logger.info('Invalidating items: %s in distro: %s', items, distro_id)
        return self.cloudfront_client.create_invalidation(
            DistributionId=distro_id,
            InvalidationBatch={
                'Paths': {
                    'Quantity': 1,
                    'Items': [items]
                },
                'CallerReference': str(datetime.utcnow().timestamp())
            }
        )['Invalidation']['Id']

    def wait_for_invalidation_completion(self, distro_id, invalidation_id):
        max_status_checks = 10
        status_check_interval = 6

        # wait for stack "final" state
        desired_status = 'Completed'
        status_check = 0

        while status_check < max_status_checks:
            status_check += 1

            # TODO: exception handling
            status = self.cloudfront_client.get_invalidation(
                DistributionId=distro_id, Id=invalidation_id)['Invalidation']['Status']

            if status == desired_status:
                self._logger.info('Distro cache invalidation %s complete', invalidation_id)
                return True

            self._logger.info('Distro cache invalidation status is: %s - waiting...', status)

            if status_check >= max_status_checks:
                raise RuntimeError('Timed out waiting for distro cache to invalidate')

            time.sleep(status_check_interval)
