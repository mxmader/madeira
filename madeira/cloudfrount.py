import madeira
import boto3


class Cf(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._session = boto3.session.Session(profile_name=profile_name, region_name=region)
        self.cloudfront_client = self._session.client('cloudfront')
        self._logger = logger if logger else madeira.get_logger()

    def get_distro_hostname(self, app_hostname):
        for distro in self.cloudfront_client.list_distributions()['DistributionList']['Items']:
            if distro['Comment'] == f"Distribution for {app_hostname}":
                return distro['DomainName']

        return None
