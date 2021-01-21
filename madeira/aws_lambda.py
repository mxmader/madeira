import base64
import hashlib
import io
import os
import time
import zipfile
from io import BytesIO

import boto3
import requests

import madeira
from madeira import sts


class AwsLambda:

    def __init__(self, logger=None):
        self.lambda_client = boto3.client('lambda')
        self._sts_wrapper = sts.Sts()
        self._logger = logger if logger else madeira.get_logger()

    @staticmethod
    def _get_zip_object():
        in_memory_zip = BytesIO()
        zip_file = zipfile.ZipFile(in_memory_zip, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)
        return in_memory_zip, zip_file

    def _get_function_zip(self, function_file_path):
        in_memory_zip, zip_file = self._get_zip_object()

        with open(function_file_path, 'r') as f:
            file_content = f.read()

        # from https://forums.aws.amazon.com/thread.jspa?threadID=239601
        zip_info = zipfile.ZipInfo('handler.py')
        zip_info.compress_type = zipfile.ZIP_DEFLATED
        zip_info.create_system = 3  # Specifies Unix
        zip_info.external_attr = 0o0777 << 16  # adjusted for python 3
        zip_file.writestr(zip_info, file_content)
        zip_file.close()

        # move file cursor to start of in-memory zip file for purposes of uploading to AWS
        in_memory_zip.seek(0)
        return in_memory_zip

    def _get_layer_zip(self, layer_path):
        in_memory_zip, zip_file = self._get_zip_object()

        cwd = os.getcwd()
        os.chdir(layer_path)
        for root, dirs, files in os.walk('.'):
            if '__pycache__' in root or not files:
                continue

            # add each file in the layer to the in-memory zip
            for file in files:
                file_path = f'{root}/{file}'
                with open(file_path, 'r') as f:
                    file_content = f.read()
                zip_info = zipfile.ZipInfo(file_path)
                zip_info.compress_type = zipfile.ZIP_DEFLATED
                zip_info.create_system = 3  # Specifies Unix
                zip_info.external_attr = 0o0777 << 16  # adjusted for python 3
                zip_file.writestr(zip_info, file_content)
        os.chdir(cwd)
        zip_file.close()
        in_memory_zip.seek(0)
        return in_memory_zip

    def _get_zip_content(self, function_file_path, function_is_zip):
        if function_is_zip:
            with open(function_file_path, 'rb') as f:
                zip_file_content = f.read()
        else:
            in_memory_zip = self._get_function_zip(function_file_path)
            zip_file_content = in_memory_zip.getvalue()

        return zip_file_content

    def _set_reserved_concurrency(self, name, reserved_concurrency):
        if reserved_concurrency:
            self._logger.info('setting reserved concurrency to %s on function %s', reserved_concurrency, name)
            self.lambda_client.put_function_concurrency(
                FunctionName=name, ReservedConcurrentExecutions=reserved_concurrency)

    def _wait_for_availability(self, function_arn):
        max_status_checks = 10
        status_check_interval = 20

        # wait for stack "final" state
        status_check = 0
        finished_status = 'Active'

        while status_check < max_status_checks:
            status_check += 1
            lambda_function = self.lambda_client.get_function(FunctionName=function_arn)

            if lambda_function['Configuration']['State'] == finished_status:
                self._logger.debug(
                    "Lambda function %s is now: %s", lambda_function["Configuration"]["FunctionName"], finished_status
                )
                return

            self._logger.debug(
                "Lambda function: %s status is: %s - waiting for status: %s",
                lambda_function["Configuration"]["FunctionName"],
                lambda_function['Configuration']['State'],
                finished_status)

            if status_check >= max_status_checks:
                raise RuntimeError(
                    "Timed out waiting for lambda function: %s to be available",
                    lambda_function["Configuration"]["FunctionName"])

            time.sleep(status_check_interval)

    def add_permission_for_s3_bucket(self, name, bucket):
        self.remove_permission_for_s3_bucket(name, bucket)
        self._logger.info('Allowing invocation of function: %s based on events from S3 bucket: %s', name, bucket)
        self.lambda_client.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName=name,
            Principal='s3.amazonaws.com',
            SourceAccount=self._sts_wrapper.get_account_id(),
            SourceArn=f'arn:aws:s3:::{bucket}',
            StatementId=f'permission_for_{bucket}'
        )

    def create_or_update_function(self, name, role, function_file_path, description='', vpc_config=None,
                                  memory_size=128, timeout=30, reserved_concurrency=None, layer_arns=None,
                                  function_is_zip=False, layer_updates=None):
        if not layer_updates:
            layer_updates = []

        try:
            lambda_function = self.lambda_client.get_function(FunctionName=name)
            self._logger.info('Function: %s already exists - determining if update is required', name)
            function_arn = lambda_function['Configuration']['FunctionArn']

            # Calculate the SHA256 checksum of the file (whether a zip file or not)
            file_sha256 = hashlib.sha256()
            with open(function_file_path, 'rb') as f:
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    file_sha256.update(data)
            file_sha256_string = base64.b64encode(file_sha256.digest()).decode()

            # for "pure python file" lambdas, we need to download the AWS encapsulation of the file (their zipped copy)
            # extract it, and compare the hash of _that_ file to the hash of the python file.
            if not function_is_zip:
                # NOTE: reads the whole zip in memory - we're assuming all lambdas stay relatively small
                r = requests.get(lambda_function.get('Code').get('Location'))
                z = zipfile.ZipFile(io.BytesIO(r.content))
                handler_content = z.read('handler.py')
                aws_file_sha256 = hashlib.sha256()
                aws_file_sha256.update(handler_content)
                aws_file_sha256_string = base64.b64encode(aws_file_sha256.digest()).decode()
            else:
                aws_file_sha256_string = lambda_function.get('Configuration').get('CodeSha256')

            if file_sha256_string != aws_file_sha256_string:
                self._logger.info('Updating lambda for code change')
            elif any(layer_updates):
                self._logger.info('Updating lambda for related layer change')
            else:
                self._logger.info('No lambda function code change and no layer related layer changes; '
                                  'no lambda function update required')
                return function_arn

            self.update_function(
                name, role, function_file_path, description=description, vpc_config=vpc_config,
                memory_size=memory_size, timeout=timeout, reserved_concurrency=reserved_concurrency,
                layer_arns=layer_arns, function_is_zip=function_is_zip)

        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.info('Function: %s does not yet exist', name)
            function_arn = self.create_function(
                name, role, function_file_path, description=description, vpc_config=vpc_config, memory_size=memory_size,
                timeout=timeout, reserved_concurrency=reserved_concurrency, layer_arns=layer_arns,
                function_is_zip=function_is_zip)

        # VPC-scoped lambdas sometimes take more time to spin up, so we wait for their final state
        if vpc_config:
            self._wait_for_availability(function_arn)

        return function_arn

    def delete_function(self, name, qualifier=None):
        args = {'FunctionName': name}
        if qualifier:
            args['Qualifier'] = qualifier

        try:
            self.lambda_client.delete_function(**args)
            self._logger.info('Function: %s deleted', name)
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.warning('Function: %s does not exist', name)

    def delete_layer_version(self, name, version):
        try:
            self.lambda_client.delete_layer_version(LayerName=name, VersionNumber=version)
            self._logger.info('Layer: %s version: %s deleted', name, version)
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.warning('Layer: %s version: %s does not exist', name, version)

    # DEPRECATED
    def create_function(self, name, role, function_file_path, description='', vpc_config=None, memory_size=128,
                        timeout=30, reserved_concurrency=None, layer_arns=None, function_is_zip=False):
        if not layer_arns:
            layer_arns = []

        if not vpc_config:
            vpc_config = {}

        self._logger.info('Deploying function: %s from file: %s', name, function_file_path)
        try:
            function_arn = self.lambda_client.create_function(
                FunctionName=name,
                Runtime='python3.7',
                Role=role,
                Handler='handler.handler',
                Code={'ZipFile': self._get_zip_content(function_file_path, function_is_zip)},
                Description=description,
                Timeout=timeout,
                Layers=layer_arns,
                MemorySize=memory_size,
                Publish=True,
                VpcConfig=vpc_config).get('FunctionArn')

        except self.lambda_client.exceptions.ResourceConflictException:
            self._logger.warning('Function: %s already exists', name)
            function_arn = self.lambda_client.get_function(FunctionName=name).get('Configuration').get('FunctionArn')

        if reserved_concurrency:
            self._set_reserved_concurrency(name, reserved_concurrency)

        return function_arn

    def deploy_layer(self, name, layer_path, description='', runtimes=None, format='directory'):
        # for layers that consist simply of a flat directory (no subdirs) with code (text) files.
        if format == 'directory':
            in_memory_zip = self._get_layer_zip(layer_path)
            zip_file_bytes = in_memory_zip.getvalue()

        # for layers with more complexity that are better off "just zipped"
        elif format == 'zipfile':
            with open(layer_path, 'rb') as f:
                zip_file_bytes = f.read()
        else:
            raise RuntimeError(f'Unsupported deployment format: {format}')

        file_sha256 = hashlib.sha256()
        file_sha256.update(zip_file_bytes)
        file_sha256_string = base64.b64encode(file_sha256.digest()).decode()

        for lambda_layer_version in self.list_layer_versions(name):
            layer_version_meta = self.lambda_client.get_layer_version_by_arn(
                Arn=lambda_layer_version['LayerVersionArn'])
            aws_sha256_string = layer_version_meta['Content']['CodeSha256']
            if aws_sha256_string == file_sha256_string:
                self._logger.info('Layer with ARN: %s is already current', lambda_layer_version['LayerVersionArn'])
                return lambda_layer_version['LayerVersionArn'], False

        if not runtimes:
            runtimes = ['python3.7']
            self._logger.debug('Using default runtimes: %s', runtimes)

        self._logger.info('deploying layer: %s in path: %s', name, layer_path)
        layer_arn = self.lambda_client.publish_layer_version(
            LayerName=name,
            Description=description,
            # must be a 'bytes' object
            Content={'ZipFile': zip_file_bytes},
            CompatibleRuntimes=runtimes).get('LayerVersionArn')
        self._logger.debug('layer ARN: %s', layer_arn)
        return layer_arn, True

    def list_functions(self):
        response = self.lambda_client.list_functions()
        functions = response.get('Functions')

        while response.get('NextMarker'):
            response = self.lambda_client.list_functions(NextMarker=response.get('NextMarker'))
            functions.extend(response.get('Functions'))

        return functions

    def list_layers(self):
        return self.lambda_client.list_layers().get('Layers')

    def list_layer_versions(self, name):
        response = self.lambda_client.list_layer_versions(LayerName=name)
        layer_versions = response.get('LayerVersions')

        while response.get('NextMarker'):
            response = self.lambda_client.list_layer_versions(LayerName=name, NextMarker=response.get('NextMarker'))
            layer_versions.extend(response.get('LayerVersions'))

        return layer_versions

    def remove_permission_for_s3_bucket(self, name, bucket):
        self._logger.info('Attempting to remove permission to invoke function: %s based on events from S3 bucket: %s '
                          'if any', name, bucket)
        try:
            self.lambda_client.remove_permission(FunctionName=name, StatementId=f'permission_for_{bucket}')
        # NOTE: there's no clean way to first look up if a permission exists before removing it without re-arranging
        # this module, so for now we just catch the exception and move on.
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.warning('Permission does not yet exist to invoke function: %s based on events from '
                                 'S3 bucket: %s', name, bucket)

    # DEPRECATED
    def update_function(self, name, role, function_file_path, description='', vpc_config=None, memory_size=128,
                        timeout=30, reserved_concurrency=None, layer_arns=None, function_is_zip=False):
        if not layer_arns:
            layer_arns = []

        if not vpc_config:
            vpc_config = {}

        self._logger.info('Updating code')
        self.lambda_client.update_function_code(
            FunctionName=name,
            ZipFile=self._get_zip_content(function_file_path, function_is_zip),
            Publish=True
        )
        self._logger.info('Updating function configuration')
        self.lambda_client.update_function_configuration(
            FunctionName=name,
            Role=role,
            Description=description,
            VpcConfig=vpc_config,
            Timeout=timeout,
            MemorySize=memory_size,
            Layers=layer_arns
        )

        if reserved_concurrency:
            self._set_reserved_concurrency(name, reserved_concurrency)
