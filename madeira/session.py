import boto3
from madeira_utils import loggers

session_store = {}

class Session(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()

        # re-use an already-instantiated session, if possible
        profile_key = profile_name if profile_name else 'default_profile'
        region_key = region if region else 'default_region'
        session_key = f"{profile_key}:{region_key}"

        if session_key in session_store:
            self._logger.debug('Using session: %s from session store', session_key)
            self.session = session_store[session_key]
        else:
            self._logger.debug('Creating new boto3 session')
            self.session = boto3.Session(profile_name=profile_name, region_name=region)
            self._logger.debug('Saving session: %s in session store', session_key)
            session_store[session_key] = self.session

        # for convenience
        self.profile_name = self.session.profile_name
        self.region = self.session.region_name
