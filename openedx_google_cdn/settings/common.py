"""Common environment variables unique to the discussion plugin."""


def plugin_settings(settings):
    """Settings for the google_cdn plugin. """
    settings.FEATURES['ALLOW_HIDING_DISCUSSION_TAB'] = False
    settings.DISCUSSION_SETTINGS = {
        'MAX_COMMENT_DEPTH': 2,
        'COURSE_PUBLISH_TASK_DELAY': 30,
    }
    settings.OVERRIDE_GENERATE_VIDEO_UPLOAD_LINK = 'openedx_google_cdn.views.custom_video_upload_link_generator'
    settings.OVERRIDE_HANDLE_VIDEOS = 'openedx_google_cdn.views.enhanced_handle_videos'
    settings.ENABLE_GOOGLE_CDN = 'True'
    settings.GOOGLE_CDN_BUCKET = 'cehck1123'