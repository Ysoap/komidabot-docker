from flask import current_app as _current_app


def get_app() -> 'App':
    return _current_app


class App:
    def __init__(self, config):
        import atexit
        from concurrent.futures import ThreadPoolExecutor as PyThreadPoolExecutor

        from komidabot.facebook.api_interface import ApiInterface
        from komidabot.facebook.messenger import Messenger
        from komidabot.facebook.users import UserManager as FacebookUserManager
        from komidabot.komidabot import Komidabot
        from komidabot.users import UnifiedUserManager

        self.bot_interfaces = dict()  # TODO: Deprecate?
        self.bot_interfaces['facebook'] = {
            'api_interface': ApiInterface(config.get('PAGE_ACCESS_TOKEN')),
            'messenger': Messenger(config.get('PAGE_ACCESS_TOKEN'), config.get('ADMIN_IDS_LEGACY')),  # TODO: Deprecated
            'users': FacebookUserManager()
        }

        self.user_manager = UnifiedUserManager()
        self.user_manager.register_manager('facebook', self.bot_interfaces['facebook']['users'])

        self.messenger = self.bot_interfaces['facebook']['messenger']  # TODO: Deprecated
        self.komidabot = self.bot = Komidabot(self)  # TODO: Deprecate self.komidabot?

        # TODO: This could probably also be moved to the Komidabot class
        self.task_executor = PyThreadPoolExecutor(max_workers=5)
        atexit.register(PyThreadPoolExecutor.shutdown, self.task_executor)  # Ensure cleanup of resources

        self.user_manager.initialise()

        self.admin_ids = get_app().config.get('ADMIN_IDS', [])

    def app_context(self):
        raise NotImplementedError()

    @property
    def config(self):
        raise NotImplementedError()

    def _get_current_object(self):
        raise NotImplementedError
