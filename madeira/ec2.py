import madeira
import boto3
import botocore.exceptions


class Ec2(object):
    def __init__(self, logger=None):
        self._logger = logger if logger else madeira.get_logger()
        self.ec2_client = boto3.client("ec2")

    def assure_key_pair(self, key_name, key_material):
        try:
            self.ec2_client.describe_key_pairs(KeyNames=[key_name])
            self._logger.info("Key pair with already exists with name: %s", key_name)
        except botocore.exceptions.ClientError as e:
            if "does not exist" in str(e):
                self._logger.info("Importing SSH public key as: %s", key_name)
                self.ec2_client.import_key_pair(
                    KeyName=key_name, PublicKeyMaterial=key_material
                )
            else:
                raise

    def delete_key_pair(self, key_name):
        self._logger.info("Deleting EC2 key pair: %s", key_name)
        self.ec2_client.delete_key_pair(KeyName=key_name)

    def disable_termination_protection(self, instance_id):
        return self.ec2_client.modify_instance_attribute(
            InstanceId=instance_id, DisableApiTermination={"Value": False}
        )

    def list_instances(self):
        return self.ec2_client.describe_instances().get("Reservations")
