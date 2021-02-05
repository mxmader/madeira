from datetime import datetime
import time

from madeira import session, s3
from madeira_utils import loggers


class CloudFront(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)

        self.cloudfront_client = self._session.session.client('cloudfront')
        self._s3 = s3.S3(logger=None, profile_name=None, region=None)

    def get_distribution_by_comment(self, comment):
        for distro in self.cloudfront_client.list_distributions()['DistributionList']['Items']:
            if distro['Comment'] == comment:
                return distro

    def invalidate_cache(self, distro_id, items=None):
        if not items:
            items = ['/*']

        self._logger.info('Invalidating items: %s in distro: %s', items, distro_id)

        return self.cloudfront_client.create_invalidation(
            DistributionId=distro_id,
            InvalidationBatch={
                'Paths': {
                    'Quantity': len(items),
                    'Items': items
                },
                'CallerReference': str(datetime.utcnow().timestamp())
            }
        )['Invalidation']['Id']

    def update_cdn_content(self, cdn_id, bucket, files):
        changed_files = self._s3.sync_files(bucket, files)
        for i, changed_file in enumerate(changed_files):
            if not changed_file.startswith('/'):
                changed_files[i] = f'/{changed_file}'

        # invalidate the cloudfront cache if any assets are changed
        if changed_files:
            self._logger.info("One or more asset files have changed")
            invalidation_id = self.invalidate_cache(cdn_id, items=changed_files)
            self.wait_for_invalidation_completion(cdn_id, invalidation_id)
        else:
            self._logger.info("No asset file changes detected; skipping distro cache invalidation")

    def wait_for_invalidation_completion(self, distro_id, invalidation_id):
        max_status_checks = 10
        status_check_interval = 10

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

            self._logger.info('Distro cache invalidation %s status is: %s - waiting', invalidation_id, status)

            if status_check >= max_status_checks:
                raise RuntimeError('Timed out waiting for invalidation %s', invalidation_id)

            time.sleep(status_check_interval)
