import madeira
import boto3


class CloudWatch(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else madeira.get_logger()
        self._session = boto3.session.Session(profile_name=profile_name, region_name=region)
        self.cloudwatch_logs_client = self._session.client('logs')

    def set_log_group_retention(self, log_group, days):
        return self.cloudwatch_logs_client.put_retention_policy(logGroupName=log_group, retentionInDays=days)
