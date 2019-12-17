import json
from typing import Callable, Optional

import komidabot.facebook.triggers as triggers
import komidabot.facebook.messages as fb_messages
import komidabot.messages as messages
import komidabot.models as models
import komidabot.localisation as localisation
from extensions import db

postback_mappings = {}


class Postback:
    def call_postback(self, trigger: triggers.Trigger, *args, **kwargs) -> triggers.Trigger:
        raise NotImplementedError()


def lookup_postback(name: str) -> Postback:
    return postback_mappings.get(name, None)


def postback(name: str = None):
    class PostbackDecorator(Postback):
        def __init__(self, func: Callable):
            nonlocal name

            if name is None:
                name = func.__name__

            if name in postback_mappings:
                raise ValueError('Duplicate postback identifier')

            postback_mappings[name] = self

            self.func = func
            self.__name__ = func.__name__

        def call_postback(self, trigger: triggers.Trigger, *args, **kwargs) -> Optional[triggers.Trigger]:
            return self.func(trigger, *args, **kwargs)

        def __call__(self, *args, **kwargs):
            return json.dumps({'name': name, 'args': args, 'kwargs': kwargs})

    return PostbackDecorator


def postback_button(title: str, payload: str):
    return {'type': 'postback', 'title': title, 'payload': payload}


@postback(name='komidabot:get_started')
def get_started(trigger: triggers.Trigger):
    if triggers.NewUserAspect not in trigger:
        trigger.add_aspect(triggers.NewUserAspect())
    return trigger


@postback(name='komidabot:menu_today')
def menu_today(trigger: triggers.Trigger):
    return trigger


@postback(name='komidabot:settings_subscriptions')
def settings_subscriptions(trigger: triggers.Trigger):
    if triggers.SenderAspect not in trigger:
        raise ValueError('Trigger missing SenderAspect')
    sender = trigger[triggers.SenderAspect].sender
    locale = sender.get_locale()

    if not sender.is_feature_active('menu_subscription'):
        sender.send_message(messages.TextMessage(trigger, localisation.REPLY_FEATURE_UNAVAILABLE(locale)))
        return None

    elements_list = [[]]

    campuses = models.Campus.get_all_active()

    for day in models.week_days:
        elements = []

        title = localisation.DAYS[day.value - 1](locale)
        image = 'https://komidabot.heldplayer.blue/images/{}.png'.format(day.name.lower())
        buttons = [postback_button(localisation.UNSUBSCRIBE(locale), set_subscription(1, None))]

        for campus in campuses:
            buttons.append(postback_button(campus.name, set_subscription(day.value, campus.id)))

        for i in range(0, len(buttons), 3):
            elements.append({
                'title': title if i == 0 else (title + localisation.CONTINUATION(locale)),
                'image_url': image,
                'buttons': buttons[i:i + 3]
            })

        if len(elements_list[-1]) + len(elements) > 10:
            elements_list.append([])

        elements_list[-1].extend(elements)

    for elements in elements_list:
        payload = {
            'template_type': 'generic',
            'elements': elements,
        }
        sender.send_message(fb_messages.TemplateMessage(trigger, payload))

    return None


@postback(name='komidabot:set_subscription')
def set_subscription(trigger: triggers.Trigger, day: int, campus: Optional[int]):
    if triggers.SenderAspect not in trigger:
        raise ValueError('Trigger missing SenderAspect')
    sender = trigger[triggers.SenderAspect].sender
    db_user = sender.get_db_user()
    locale = sender.get_locale()

    if not sender.is_feature_active('menu_subscription'):
        sender.send_message(messages.TextMessage(trigger, localisation.REPLY_FEATURE_UNAVAILABLE(locale)))
        return None

    selected_day = models.Day(day)
    selected_campus = None

    if campus is None:
        db_user.set_day_active(selected_day, False)
    else:
        selected_campus = models.Campus.get_by_id(campus)
        db_user.set_campus(selected_day, selected_campus, active=True)

    db.session.commit()

    msg = localisation.REPLY_SET_SUBSCRIPTION(locale).format(day=localisation.DAYS[day - 1](locale),
                                                             campus=localisation.UNSUBSCRIBED(locale)
                                                             if selected_campus is None else selected_campus.name)
    sender.send_message(messages.TextMessage(trigger, msg))

    return None


@postback(name='komidabot:settings_language')
def settings_language(trigger: triggers.Trigger):
    if triggers.SenderAspect not in trigger:
        raise ValueError('Trigger missing SenderAspect')
    sender = trigger[triggers.SenderAspect].sender

    payload = {
        'template_type': 'button',
        'text': 'Chose your desired language',
        'buttons': [
            postback_button("Nederlands", set_language('nl_BE', 'Nederlands')),
            postback_button("English", set_language('en_US', 'English')),
            postback_button("From Facebook", set_language('', 'From Facebook')),
        ],
    }
    sender.send_message(fb_messages.TemplateMessage(trigger, payload))

    return None


@postback(name='komidabot:set_language')
def set_language(trigger: triggers.Trigger, language: str, display: str):
    if triggers.SenderAspect not in trigger:
        raise ValueError('Trigger missing SenderAspect')
    sender = trigger[triggers.SenderAspect].sender
    db_user = sender.get_db_user()
    locale = sender.get_locale()

    db_user.set_language(language)
    db.session.commit()

    sender.send_message(messages.TextMessage(trigger, localisation.REPLY_SET_LANGUAGE(locale).format(language=display)))

    return None


def generate_postback_data(include_persistent_menu: bool):
    result = dict()
    result['get_started'] = {
        'payload': get_started(),
    }
    result['greeting'] = [
        {
            'locale': 'default',
            'text': 'Welcome!',
        },
        {
            'locale': 'nl_BE',
            'text': 'Welkom!',
        },
        {
            'locale': 'nl_NL',
            'text': 'Welkom!',
        },
    ]
    if include_persistent_menu:
        # TODO: Once per-user persistent menus are available, use them
        #       https://developers.facebook.com/docs/messenger-platform/send-messages/persistent-menu/
        result['persistent_menu'] = [
            {
                'locale': 'default',
                'composer_input_disabled': False,
                'call_to_actions': [
                    postback_button("Today's menu", menu_today()),
                    postback_button("Manage subscription", settings_subscriptions()),
                    postback_button("Change language", settings_language()),
                ],
            },
        ]

    return result
