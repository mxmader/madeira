from madeira import session
from madeira_utils import loggers


class Kms(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.kms_client = self._session.session.client('kms')

    def get_key(self, key_id):
        return self.kms_client.describe_key(KeyId=key_id)

    def get_key_arn(self, key_id):
        try:
            return self.get_key(key_id).get('KeyMetadata').get('Arn')
        except self.kms_client.exceptions.NotFoundException:
            return False
