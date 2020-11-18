import boto3


class Redshift(object):
    def __init__(self):
        self.client = boto3.client('redshift')

    def get_clusters(self):
        return self.client.describe_clusters()
