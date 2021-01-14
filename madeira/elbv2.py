import madeira
import boto3


class ElbV2(object):

    def __init__(self, logger=None):
        self._logger = logger if logger else madeira.get_logger()
        self.elbv2_client = boto3.client('elbv2')

    def disable_termination_protection(self, arn):
        return self.elbv2_client.modify_load_balancer_attributes(
            LoadBalancerArn=arn,
            Attributes=[{'Key': 'deletion_protection.enabled', 'Value': 'false'}]
        )

    def get_load_balancer_fqdn(self, name):
        return self.elbv2_client.describe_load_balancers(Names=[name])['LoadBalancers'][0]['DNSName']

    def list_load_balancers(self):
        return self.elbv2_client.describe_load_balancers().get('LoadBalancers')
