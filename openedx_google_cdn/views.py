import json
import logging
import tempfile
from uuid import uuid4

from django.conf import settings
from django.http import HttpResponseNotFound
from django.utils.translation import gettext as _
from pytz import UTC
from rest_framework import status as rest_status
from rest_framework.response import Response

from common.djangoapps.util.json_request import JsonResponse
from cms.djangoapps.contentstore.toggles import use_mock_video_uploads
from cms.djangoapps.contentstore.video_storage_handlers import (
    _get_and_validate_course,
    videos_index_json,
    _generate_pagination_configuration,
    videos_index_html,
    is_status_update_request,
    _is_pagination_context_update_request,
    _update_pagination_context,
    send_video_status_update,
    videos_post,
)
from edxval.api import (
    create_video,
    get_transcript_preferences,
    remove_video_for_course,
)
from openedx.core.djangoapps.video_config.models import VideoTranscriptEnabledFlag
from xmodule.exceptions import NotFoundError
from xmodule.video_block.transcripts_utils import Transcript
from xmodule.video_block.video_block import VideoBlock

try:
    import edxval.api as edxval_api
except ImportError:
    edxval_api = None

LOGGER = logging.getLogger(__name__)

VIDEO_SUPPORTED_FILE_FORMATS = {
    '.mp4': 'video/mp4',
    '.mov': 'video/quicktime',
}


KEY_EXPIRATION_IN_SECONDS = 86400



def enhanced_handle_videos(prev_fn, request, course_key_string, edx_video_id=None):
    
    course = _get_and_validate_course(course_key_string, request.user)

    if (not course and not use_mock_video_uploads()):
        return HttpResponseNotFound()

    if request.method == "GET":
        if "application/json" in request.META.get("HTTP_ACCEPT", ""):
            return videos_index_json(course)
        pagination_conf = _generate_pagination_configuration(course_key_string, request)
        return videos_index_html(course, pagination_conf)
    elif request.method == "DELETE":
        remove_video_for_course(course_key_string, edx_video_id)
        return JsonResponse()
    else:
        if is_status_update_request(request.json):
            return send_video_status_update(request.json)
        elif _is_pagination_context_update_request(request):
            return _update_pagination_context(request)

        if getattr(settings, "ENABLE_GOOGLE_CDN", None):
            data, status = videos_post_cdn(course, request)
        else:
            data, status = videos_post(course, request)
        return JsonResponse(data, status=status)
    
def custom_video_upload_link_generator(prev_fn, request, course_key_string):
    """
    API for creating a video upload.  Returns an edx_video_id and a presigned URL that can be used
    to upload the video to AWS S3.
    """
    course = _get_and_validate_course(course_key_string, request.user)
    if not course:
        return Response(data='Course Not Found', status=rest_status.HTTP_400_BAD_REQUEST)

    if getattr(settings, "ENABLE_GOOGLE_CDN", None):
        data, status = videos_post_cdn(course, request)
    else:
        data, status = videos_post(course, request)
    return Response(data, status=status)

def videos_post_cdn(course, request):
    """
    Input (JSON):
    {
        "files": [{
            "file_name": "video.mp4",
            "content_type": "video/mp4"
        }]
    }
    Returns (JSON):
    {
        "files": [{
            "file_name": "video.mp4",
            "upload_url": "http://example.com/put_video"
        }]
    }
    The returned array corresponds exactly to the input array.
    """
    error = None
    data = request.json
    if 'files' not in data:
        error = "Request object is not JSON or does not contain 'files'"
    elif any(
        'file_name' not in file or 'content_type' not in file
        for file in data['files']
    ):
        error = "Request 'files' entry does not contain 'file_name' and 'content_type'"
    elif any(
        file['content_type'] not in list(VIDEO_SUPPORTED_FILE_FORMATS.values())
        for file in data['files']
    ):
        error = "Request 'files' entry contain unsupported content_type"

    if error:
        return {'error': error}, 400

    bucket = cdn_storage_service_bucket()
    req_files = data['files']
    resp_files = []

    for req_file in req_files:
        file_name = req_file['file_name']

        try:
            file_name.encode('ascii')
        except UnicodeEncodeError:
            error_msg = 'The file name for %s must contain only ASCII characters.' % file_name
            return {'error': error_msg}, 400

        edx_video_id = str(uuid4())

        cdn_key = cdn_storage_service_key(bucket, file_name=edx_video_id)

        metadata_list = [
            ('client_video_id', file_name),
            ('course_key', str(course.id)),
        ]

        is_video_transcript_enabled = VideoTranscriptEnabledFlag.feature_enabled(course.id)
        if is_video_transcript_enabled:
            transcript_preferences = get_transcript_preferences(str(course.id))
            if transcript_preferences is not None:
                metadata_list.append(('transcript_preferences', json.dumps(transcript_preferences)))

        metadata = {}
        for metadata_name, value in metadata_list:
            metadata[metadata_name] = value

        cdn_key.metadata = metadata

        upload_url = cdn_key.generate_signed_url(
            version="v4",
            expiration=KEY_EXPIRATION_IN_SECONDS,
            method="PUT",
            content_type=req_file['content_type'],
        )
        
        if getattr(settings, "ENABLE_GOOGLE_CDN", None):
            source_url = "{}/{}/{}".format(
                settings.GOOGLE_CDN_HOST,
                settings.VIDEO_UPLOAD_PIPELINE.get("ROOT_PATH", ""),
                edx_video_id
            )
        else:
            source_url = None

        # persist edx_video_id in VAL
        create_video({
            'edx_video_id': edx_video_id,
            'status': 'upload',
            'client_video_id': file_name,
            'duration': 0,
            'encoded_videos': [],
            'courses': [str(course.id)],
            'html5_sources': [source_url] if source_url else []
        })

        resp_files.append({'file_name': file_name, 'upload_url': upload_url, 'edx_video_id': edx_video_id})

    return {'files': resp_files}, 200


def cdn_storage_service_bucket():
    """Generates a v4 signed URL for uploading a blob using HTTP PUT.
    Note that this method requires a service account key file. You can not use
    this if you are using Application Default Credentials from Google Compute
    Engine or from the Google Cloud SDK.
    """

    bucket_name = settings.GOOGLE_CDN_BUCKET
    credentials = settings.GOOGLE_CDN_CREDENTIALS
    
    # Convert the dictionary to a JSON-formatted string
    credentials_json = json.dumps(credentials)

    temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False)

    # Write the JSON string to the temporary file
    temp_file.write(credentials_json)

    # Close the file before passing its path to the function
    temp_file.close()
    # Use the temporary file path in your function
    storage_client = storage.Client.from_service_account_json(temp_file.name)
    return storage_client.bucket(bucket_name)


def cdn_storage_service_key(bucket, file_name):
    """
    Returns an S3 key to the given file in the given bucket.
    """
    key_name = "{}/{}".format(
        settings.VIDEO_UPLOAD_PIPELINE.get("ROOT_PATH", ""),
        file_name
    )
    return bucket.blob(key_name)



class CustomVideoBlock(VideoBlock):
    def editor_saved(self, user, old_metadata, old_content):
        """
        Custom logic to update video values during `self`:save method from CMS.
        Includes custom feature to set source URL to Google CDN if sub is None.
        """
        metadata_was_changed_by_user = old_metadata != self.own_metadata()

        # Custom logic for syncing issue and transcript creation
        if not metadata_was_changed_by_user and self.sub and hasattr(self, 'html5_sources'):
            html5_ids = self.get_html5_ids(self.html5_sources)
            for subs_id in html5_ids:
                try:
                    Transcript.asset(self.location, subs_id)
                except NotFoundError:
                    metadata_was_changed_by_user = True
                    break

        if metadata_was_changed_by_user:
            self.edx_video_id = self.edx_video_id and self.edx_video_id.strip()

            # Custom SDAIA Feature: Set source URL to Google CDN if sub is None
            if self.edx_video_id and not self.sub and getattr(settings, "ENABLE_GOOGLE_CDN", None):
                source_url = "{}/{}/{}".format(
                    settings.GOOGLE_CDN_HOST,
                    settings.VIDEO_UPLOAD_PIPELINE.get("ROOT_PATH", ""),
                    self.edx_video_id
                )
                self.html5_sources = [source_url]

            # Logic for overriding `youtube_id_1_0` with val youtube profile
            if self.edx_video_id and edxval_api:
                val_youtube_id = edxval_api.get_url_for_profile(self.edx_video_id, 'youtube')
                if val_youtube_id and self.youtube_id_1_0 != val_youtube_id:
                    self.youtube_id_1_0 = val_youtube_id

            # Call to manage_video_subtitles_save remains unchanged
            self.manage_video_subtitles_save(
                user,
                old_metadata if old_metadata else None,
                generate_translation=True
            )
