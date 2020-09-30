import madeira
import boto3


class RdsClusterWrapper(object):

    def __init__(self, logger=None):
        self._logger = logger if logger else madeira.get_logger()
        self._rds_client = boto3.client('rds')

    def disable_cluster_termination_protection(self, cluster_id):
        return self._rds_client.modify_db_cluster(
            DBClusterIdentifier=cluster_id,
            DeletionProtection=False
        )

    # TODO: find usage and replace with list_clusters
    def get_clusters(self):
        return self._rds_client.describe_db_clusters()

    # TODO: list_global_clusters (consistency)
    def get_global_clusters(self):
        return self._rds_client.describe_global_clusters()

    # TODO: list_instances (consistency)
    def get_instances(self):
        return self._rds_client.describe_db_instances()

    def list_clusters(self):
        return self._rds_client.describe_db_clusters().get('DBClusters')
