import boto3
import madeira


class Ecs(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._session = boto3.session.Session(profile_name=profile_name, region_name=region)
        self.ecs_client = self._session.client("ecs")
        self._account_id = (self._session.client("sts").get_caller_identity().get("Account"))
        self._logger = logger if logger else madeira.get_logger()

    def list_tasks(self, cluster):
        tasks = self.ecs_client.list_tasks(cluster=cluster).get('taskArns')

        if not tasks:
            return []

        return self.ecs_client.describe_tasks(
            cluster=cluster, tasks=tasks).get('tasks')

    def stop_tasks(self, cluster, tasks, reason=''):
        for task in tasks:
            self._logger.info('Stopping task: %s', task['taskArn'])
            self._logger.info('  Container name(s): %s', ','.join([container['name'] for container in task['containers']]))
            self.ecs_client.stop_task(cluster=cluster, task=task['taskArn'], reason=reason)
