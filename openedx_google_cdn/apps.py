"""
openedx_google_cdn Django application initialization.
"""

from django.apps import AppConfig
from openedx.core.djangoapps.plugins.constants import (
    PluginSettings, PluginURLs, ProjectType, SettingsType
)


class OpenedxGoogleCdnConfig(AppConfig):
    """
    Configuration for the openedx_google_cdn Django application.
    """

    name = 'openedx_google_cdn'
    plugin_app = {
        PluginSettings.CONFIG: {
            ProjectType.CMS: {
                SettingsType.PRODUCTION: {
                    PluginSettings.RELATIVE_PATH: "settings.production"
                },
                SettingsType.COMMON: {PluginSettings.RELATIVE_PATH: "settings.common"},
            }
        },
    }
