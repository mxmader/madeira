from madeira import session
from madeira_utils import loggers


class ElbV2(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)

        self.elbv2_client = self._session.session.client('elbv2')

    def disable_termination_protection(self, arn):
        return self.elbv2_client.modify_load_balancer_attributes(
            LoadBalancerArn=arn,
            Attributes=[{'Key': 'deletion_protection.enabled', 'Value': 'false'}]
        )

    def get_load_balancer_fqdn(self, name):
        return self.elbv2_client.describe_load_balancers(Names=[name])['LoadBalancers'][0]['DNSName']

    def list_load_balancers(self):
        return self.elbv2_client.describe_load_balancers().get('LoadBalancers')
