"""
openedx_google_cdn Django application initialization.
"""

from django.apps import AppConfig
from openedx.core.djangoapps.plugins.constants import ProjectType, SettingsType
from edx_django_utils.plugins import PluginSettings, PluginURLs


class OpenedxGoogleCdnConfig(AppConfig):
    """
    Configuration for the openedx_google_cdn Django application.
    """

    name = "openedx_google_cdn"
    plugin_app = {

        PluginSettings.CONFIG: {
            ProjectType.CMS: {
                SettingsType.COMMON: {PluginSettings.RELATIVE_PATH: 'settings.common'},
            },
            ProjectType.LMS: {
                SettingsType.COMMON: {PluginSettings.RELATIVE_PATH: 'settings.common'},
            },
        }
    }