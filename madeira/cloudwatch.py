from madeira import session
import madeira_utils


class CloudWatch(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else madeira_utils.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.cloudwatch_logs_client = self._session.session.client('logs')

    def set_log_group_retention(self, log_group, days):
        return self.cloudwatch_logs_client.put_retention_policy(logGroupName=log_group, retentionInDays=days)
