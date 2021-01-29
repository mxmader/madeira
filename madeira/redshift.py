from madeira import session
from madeira_utils import loggers


class Redshift(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.redshift_client = self._session.session.client('redshift')

    def get_clusters(self):
        return self.redshift_client.describe_clusters()
