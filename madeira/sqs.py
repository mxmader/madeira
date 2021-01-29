from madeira import session
from madeira_utils import loggers


class SQS(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self.sqs_resource = self._session.session.resource('sqs')

    def get_queue(self, name):
        return self.sqs_resource.get_queue_by_name(QueueName=name)

    def send_message(self, queue_name, message_group_id, message_body, message_attributes=None):
        return self.get_queue(queue_name).send_message(
            MessageGroupId=message_group_id,
            MessageBody=message_body,
            MessageAttributes=message_attributes)
