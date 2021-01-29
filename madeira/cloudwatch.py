from madeira import session
from madeira_utils import loggers


class CloudWatch(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.cloudwatch_logs_client = self._session.session.client('logs')

    def delete_log_groups_in_namespace(self, namespace):
        # TODO: implement NextToken support
        self._logger.debug('Getting log groups in namespace (prefixed with): %s', namespace)
        log_groups_in_namespace = self.cloudwatch_logs_client.describe_log_groups(
            logGroupNamePrefix=namespace).get('logGroups', [])
        for log_group in log_groups_in_namespace:
            self._logger.info('Deleting log group: %s', log_group['logGroupName'])
            self.cloudwatch_logs_client.delete_log_group(logGroupName=log_group['logGroupName'])

    def set_log_group_retention(self, log_group, days):
        return self.cloudwatch_logs_client.put_retention_policy(logGroupName=log_group, retentionInDays=days)
