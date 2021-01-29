from madeira import session, sts
from madeira_utils import loggers


class Ecs(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=profile_name, region=region)
        self.ecs_client = self._session.session.client("ecs")

    def list_tasks(self, cluster):
        tasks = self.ecs_client.list_tasks(cluster=cluster).get('taskArns')

        if not tasks:
            return []

        return self.ecs_client.describe_tasks(
            cluster=cluster, tasks=tasks).get('tasks')

    def stop_tasks(self, cluster, tasks, reason=''):
        results = []
        for task in tasks:
            self._logger.info('Stopping task: %s', task['taskArn'])
            self._logger.info('  Container name(s): %s', ','.join(
                [container['name'] for container in task['containers']]))
            results.append(
                self.ecs_client.stop_task(cluster=cluster, task=task['taskArn'], reason=reason))
        return results
