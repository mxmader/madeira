from madeira import session
from madeira_utils import loggers


class RdsCluster(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.rds_client = self._session.session.client('rds')

    def disable_cluster_termination_protection(self, cluster_id):
        return self.rds_client.modify_db_cluster(
            DBClusterIdentifier=cluster_id, DeletionProtection=False)

    # TODO: find usage and replace with list_clusters
    def get_clusters(self):
        return self.rds_client.describe_db_clusters()

    # TODO: list_global_clusters (consistency)
    def get_global_clusters(self):
        return self.rds_client.describe_global_clusters()

    # TODO: list_instances (consistency)
    def get_instances(self):
        return self.rds_client.describe_db_instances()

    def list_clusters(self):
        return self.rds_client.describe_db_clusters().get('DBClusters')
