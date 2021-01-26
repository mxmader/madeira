import boto3
import madeira_utils


class Session(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else madeira_utils.get_logger()
        self.session = boto3.Session(profile_name=profile_name, region_name=region)

        # for convenience
        self.profile_name = self.session.profile_name
        self.region = self.session.region_name
