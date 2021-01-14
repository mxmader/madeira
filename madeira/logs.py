import madeira
import boto3


class Logs(object):

    def __init__(self, logger=None, region=None):
        self.logs_client = boto3.client('logs', region_name=region)
        self._logger = logger if logger else madeira.get_logger()

    def get_log_groups(self):
        return self.logs_client.describe_log_groups().get('logGroups')

    def delete_log_group(self, log_group):
        return self.logs_client.delete_log_group(logGroupName=log_group)
