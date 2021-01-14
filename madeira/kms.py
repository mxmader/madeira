import madeira
import boto3


class Kms(object):

    def __init__(self, logger=None, region=None):
        self.kms_client = boto3.client('kms', region_name=region)
        self._logger = logger if logger else madeira.get_logger()

    def get_key(self, key_id):
        return self.kms_client.describe_key(KeyId=key_id)

    def get_key_arn(self, key_id):
        try:
            return self.get_key(key_id).get('KeyMetadata').get('Arn')
        except self.kms_client.exceptions.NotFoundException:
            return False
