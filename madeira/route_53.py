import madeira
import boto3


class Route_53_Wrapper(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else madeira.get_logger()
        self._session = boto3.session.Session(profile_name=profile_name, region_name=region)
        self._r53_client = self._session.client('route53')

    def create_hosted_zone(self, dns_domain):
        self._logger.debug('Creating hosted zone for DNS domain: %s', dns_domain)
        self._r53_client.
        

    def get_hosted_zone_id(self, dns_domain):
        self._logger.debug('Looking up hosted zone ID for domain: %s', dns_domain)
        for hosted_zone in self._r53_client.list_hosted_zones().get('HostedZones'):
            # Hosted zones have trailing dots...
            if hosted_zone['Name'] == '{}.'.format(dns_domain):
                return hosted_zone['Id']
        self._logger.debug('No hosted zone found')

    def get_domain_ns_records(self, hosted_zone_id):
        return self._r53_client.get_hosted_zone(Id=hosted_zone_id)['DelegationSet']['NameServers']
