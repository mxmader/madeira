from madeira import session
from madeira_utils import loggers


class Logs(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.logs_client = self._session.session.client('logs')

    def get_log_groups(self):
        return self.logs_client.describe_log_groups().get('logGroups')

    def delete_log_group(self, log_group):
        return self.logs_client.delete_log_group(logGroupName=log_group)
