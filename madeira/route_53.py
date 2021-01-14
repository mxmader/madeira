import madeira
import boto3

import uuid


class Route_53(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else madeira.get_logger()
        self._session = boto3.session.Session(profile_name=profile_name, region_name=region)
        self.r53_client = self._session.client('route53')

    def create_hosted_zone(self, dns_domain, caller_reference=None):
        caller_reference = caller_reference if caller_reference else uuid.uuid4().hex
        self._logger.debug('Creating hosted zone for DNS domain: %s', dns_domain)

        return self.r53_client.create_hosted_zone(
            Name=dns_domain, CallerReference=caller_reference)

    def delete_hosted_zone_by_name(self, dns_domain):
        return self.r53_client.delete_hosted_zone(Id=self.get_hosted_zone_id(dns_domain))

    def get_hosted_zone(self, hosted_zone_id):
        return self.r53_client.get_hosted_zone(Id=hosted_zone_id)

    def get_hosted_zone_id(self, dns_domain):
        self._logger.debug('Looking up hosted zone ID for domain: %s', dns_domain)
        for hosted_zone in self.r53_client.list_hosted_zones().get('HostedZones'):
            # Hosted zones have trailing dots...
            if hosted_zone['Name'] == f'{dns_domain}':
                return hosted_zone['Id']
        self._logger.debug('No hosted zone found')

    def get_domain_ns_records(self, hosted_zone_id):
        hosted_zone = self.get_hosted_zone(hosted_zone_id)
        return hosted_zone['DelegationSet']['NameServers']
