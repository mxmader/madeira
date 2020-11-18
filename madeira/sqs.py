import boto3


class SQS(object):

    def __init__(self, queue_name):
        self.sqs_resource = boto3.resource('sqs')
        self.queue = self.sqs_resource.get_queue_by_name(QueueName=queue_name)

    def send_message(self, message_group_id, message_body, message_attributes=None):
        return self.queue.send_message(
            MessageGroupId=message_group_id,
            MessageBody=message_body,
            MessageAttributes=message_attributes)
