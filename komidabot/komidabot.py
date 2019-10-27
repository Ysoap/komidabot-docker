import atexit, datetime, threading
from typing import Dict, List, Optional

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from komidabot.app import get_app

from komidabot.bot import Bot, ReceivedTextMessage
# from komidabot.conversations.single_message_conversation import SingleMessageConversation
from komidabot.facebook.messenger import MessageSender
import komidabot.facebook.nlp_dates as nlp_dates
import komidabot.menu
from komidabot.menu_scraper import FrameDay, FrameFoodType, MenuScraper, ParseResult, parse_price
import komidabot.messages as messages
import komidabot.triggers as triggers
import komidabot.users as users

from komidabot.models import Campus, Day, FoodType, Menu, AppUser, Translatable
from komidabot.models import create_standard_values, import_dump, recreate_db

from extensions import db


class Komidabot(Bot):
    def __init__(self, the_app):
        self.lock = threading.Lock()

        self.scheduler = BackgroundScheduler(
            jobstores={'default': MemoryJobStore()},
            executors={'default': ThreadPoolExecutor(max_workers=1)}
        )

        self.scheduler.start()
        atexit.register(BackgroundScheduler.shutdown, self.scheduler)  # Ensure cleanup of resources

        # Scheduled jobs should work with DST

        @self.scheduler.scheduled_job(CronTrigger(day_of_week='mon-fri', hour=10, minute=0, second=0),
                                      args=(the_app.app_context, self),
                                      id='daily_menu', name='Daily menu notifications')
        def daily_menu(context, bot: 'Komidabot'):
            with context():
                bot.trigger_received(triggers.SubscriptionTrigger())

        # FIXME: This is disabled for now
        # @self.scheduler.scheduled_job(CronTrigger(hour=1, minute=0, second=0),  # Run every day to find changes
        #                               args=(the_app.app_context, self),
        #                               id='menu_update', name='Daily late-night update of the menus')
        # def menu_update(context, bot: 'Komidabot'):
        #     with context():
        #         bot.update_menus(None)

    # TODO: Deprecated
    def message_received_legacy(self, message: ReceivedTextMessage):
        with self.lock:
            print('Komidabot received a legacy message', flush=True)

            # TODO: It may be an idea to keep track of active conversations
            # Simple requests to get the menu would then be conversations that end immediately
            # - Initial setup -> ask user some basic questions to get started
            # - ADMIN: Weekly menu, confirm the menu for each day/campus
            # - ADMIN: Updating configuration values

            if message.sender.is_admin():
                if message.text == 'setup':
                    recreate_db()
                    create_standard_values()
                    import_dump(get_app().config['DUMP_FILE'])
                    message.sender.send_text_message('Setup done')
                    return
                elif message.text == 'update':
                    message.sender.send_text_message('Updating menus...')
                    self.update_menus(message.sender)
                    message.sender.send_text_message('Done updating menus...')
                    return
                elif message.text == 'psid':
                    message.sender.send_text_message('Your ID is {}'.format(message.sender.get_id()))
                    return
                elif message.text == 'test':
                    # Conversation.initiate_conversation(MenuConfirmationConversation(message.sender, None), message)
                    return

            # TODO: This requires some modifications
            dates, invalid_date = nlp_dates.extract_days(message.get_attributes('datetime'))

            if invalid_date:
                message.sender.send_text_message('Sorry, I am unable to understand some of the entered dates')

            if len(dates) == 0:
                dates.append(datetime.datetime.now().date())

            if len(dates) > 1:
                message.sender.send_text_message('Sorry, please request only a single day')
                return

            campuses = Campus.get_active()
            requested_campuses = []

            for campus in campuses:
                if message.text.lower().count(campus.short_name) > 0:
                    requested_campuses.append(campus)

            user = AppUser.find_by_facebook_id(message.sender.get_id())

            for date in dates:
                day = Day(date.isoweekday())

                if day == Day.SATURDAY or day == Day.SUNDAY:
                    message.sender.send_text_message('Sorry, there are no menus on Saturdays and Sundays')
                    continue

                if len(requested_campuses) == 0:
                    if user is not None:
                        campus = user.get_campus(day)
                    if campus is None:
                        campus = Campus.get_by_short_name('cmi')
                elif len(requested_campuses) > 1:
                    message.sender.send_text_message('Sorry, please only ask for a single campus at a time')
                    continue
                else:
                    campus = requested_campuses[0]

                menu = komidabot.menu.prepare_menu_text(campus, date, message.sender.get_locale() or 'nl_BE')

                if menu is None:
                    message.sender.send_text_message('Sorry, no menu is available for {} on {}'
                                                     .format(campus.short_name.upper(), str(date)))
                else:
                    message.sender.send_text_message(menu)

    def trigger_received(self, trigger: triggers.Trigger):
        with self.lock:  # TODO: Maybe only lock on critical sections?
            app = get_app()
            print('Komidabot received a trigger: {}'.format(type(trigger).__name__), flush=True)

            if isinstance(trigger, triggers.UserTrigger):
                sender = trigger.sender

                # TODO: Is this really how we want to handle input?
                if isinstance(trigger, triggers.UserTextTrigger) and sender.is_admin():
                    text = trigger.text
                    if text == 'setup':
                        recreate_db()
                        create_standard_values()
                        import_dump(app.config['DUMP_FILE'])
                        sender.send_message(messages.TextMessage(trigger, 'Setup done'))
                        return
                    elif text == 'update':
                        sender.send_message(messages.TextMessage(trigger, 'Updating menus...'))
                        self.update_menus(None)
                        sender.send_message(messages.TextMessage(trigger, 'Done updating menus...'))
                        return
                    elif text == 'psid':  # TODO: Deprecated?
                        # message = messages.TextMessage(trigger, 'Your ID is {}'.format(sender.id.id))
                        # app.conversations.initiate_conversation(SingleMessageConversation, sender, message,
                        #                                         notify=False)
                        sender.send_message(messages.TextMessage(trigger, 'Your ID is {}'.format(sender.id.id)))
                        return

                # FIXME: This code is an adapted copy of the old path and should be rewritten
                # BEGIN DEPRECATED CODE
                date = None

                if isinstance(trigger, triggers.AnnotatedTextTrigger):
                    dates, invalid_date = nlp_dates.extract_days(trigger.get_attributes('datetime'))

                    if invalid_date:
                        sender.send_message(messages.TextMessage(trigger,
                                                                 'Sorry, I am unable to understand the requested day'))

                    if len(dates) > 1:
                        sender.send_message(messages.TextMessage(trigger, 'Sorry, please request only a single day'))
                        return
                    elif len(dates) == 1:
                        date = dates[0]

                if date is None:
                    date = datetime.datetime.now().date()

                day = Day(date.isoweekday())

                if day == Day.SATURDAY or day == Day.SUNDAY:
                    sender.send_message(messages.TextMessage(trigger,
                                                             'Sorry, there are no menus on Saturdays and Sundays'))
                    return

                campuses = Campus.get_active()
                requested_campuses = []

                for campus in campuses:
                    if trigger.text.lower().count(campus.short_name) > 0:
                        requested_campuses.append(campus)

                if len(requested_campuses) == 0:
                    campus = sender.get_campus_for_day(date)
                    if campus is None:
                        campus = Campus.get_by_short_name('cmi')
                elif len(requested_campuses) > 1:
                    sender.send_message(messages.TextMessage(trigger,
                                                             'Sorry, please only ask for a single campus at a time'))
                    return
                else:
                    campus = requested_campuses[0]

                menu = komidabot.menu.prepare_menu_text(campus, date, sender.get_locale() or 'nl_BE')

                if menu is None:
                    sender.send_message(messages.TextMessage(trigger, 'Sorry, no menu is available for {} on {}'
                                                             .format(campus.short_name.upper(), str(date))))
                else:
                    sender.send_message(messages.TextMessage(trigger, menu))
                # END DEPRECATED CODE

            if isinstance(trigger, triggers.SubscriptionTrigger):
                date = trigger.date or datetime.datetime.now().date()
                day = Day(date.isoweekday())

                # print('Sending out subscription for {} ({})'.format(date, day.name), flush=True)

                user_manager = get_app().user_manager  # type: users.UserManager
                subscribed_users = user_manager.get_subscribed_users(day)
                subscriptions = dict()  # type: Dict[Campus, Dict[str, List[users.User]]]

                for user in subscribed_users:
                    if not user.is_feature_active('menu_subscription'):
                        # print('User {} not eligible for subscription'.format(user.id), flush=True)
                        continue

                    subscription = user.get_subscription_for_day(date)
                    if subscription is None:
                        continue
                    if not subscription.active:
                        continue

                    campus = subscription.campus

                    language = user.get_locale() or 'nl_BE'

                    if campus not in subscriptions:
                        subscriptions[campus] = dict()

                    if language not in subscriptions[campus]:
                        subscriptions[campus][language] = list()

                    subscriptions[campus][language].append(user)

                for campus, languages in subscriptions.items():
                    for language, sub_users in languages.items():
                        # print('Preparing menu for {} in {}'.format(campus.short_name, language), flush=True)

                        menu = komidabot.menu.prepare_menu_text(campus, date, language)
                        if menu is None:
                            continue

                        for user in sub_users:
                            # print('Sending menu for {} in {} to {}'.format(campus.short_name, language, user.id),
                            #       flush=True)
                            user.send_message(messages.TextMessage(trigger, menu))

    # noinspection PyMethodMayBeStatic
    def update_menus(self, initiator: 'Optional[MessageSender]'):
        session = db.session  # FIXME: Create new session

        # TODO: Store a hash of the source file for each menu to check for changes
        campus_list = Campus.get_active()

        for campus in campus_list:
            scraper = MenuScraper(campus)

            scraper.find_pdf_location()

            # initiator.send_text_message('Campus {}\n{}'.format(campus.name, scraper.pdf_location))

            scraper.download_pdf()
            scraper.generate_pictures()
            parse_result = scraper.parse_pdf()

            for day in range(parse_result.start_date.toordinal(), parse_result.end_date.toordinal() + 1):
                date = datetime.date.fromordinal(day)

                menu = Menu.get_menu(campus, date)

                if menu is not None:
                    menu.delete(session=session)

                menu = Menu.create(campus, date, session=session)

                day_menu: List[ParseResult] = [result for result in parse_result.parse_results
                                               if result.day.value == date.isoweekday()
                                               or result.day == FrameDay.WEEKLY]
                # if result.day.value == date.isoweekday() or result.day.value == -1]
                # TODO: Fix pasta!
                # TODO: Fix grill stadscampus -> meerdere grills op een week
                # TODO: This may not be necessary in the near future

                for item in day_menu:
                    if item.name == '':
                        continue
                    if item.price == '':
                        continue

                    prices = parse_price(item.price)

                    if prices is None:
                        continue  # No price parsed

                    translatable, translation = Translatable.get_or_create(item.name, 'nl_NL', session=session)
                    if item.food_type == FrameFoodType.SOUP:
                        food_type = FoodType.SOUP
                    elif item.food_type == FrameFoodType.VEGAN:
                        food_type = FoodType.VEGAN
                    elif item.food_type == FrameFoodType.MEAT:
                        food_type = FoodType.MEAT
                    elif item.food_type == FrameFoodType.GRILL:
                        food_type = FoodType.GRILL
                    else:
                        continue  # TODO: Fix pasta!

                    print((translatable, food_type, prices[0], prices[1]), flush=True)

                    menu.add_menu_item(translatable, food_type, prices[0], prices[1], session=session)

            db.session.commit()

            # for result in parse_result.parse_results:
            #     print('{}/{}: {} ({})'.format(result.day.name, result.food_type.name, result.name, result.price),
            #           flush=True)
