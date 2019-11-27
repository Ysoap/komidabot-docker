import datetime
from typing import Optional

import komidabot.localisation as localisation
import komidabot.models as models
import komidabot.translation as translation


def get_menu_line(menu_item: models.MenuItem, translator: translation.TranslationService, locale: str = None) -> str:
    translation_obj = menu_item.get_translation(locale, translator)

    if not menu_item.price_staff:
        price_str = models.MenuItem.format_price(menu_item.price_students)
    else:
        price_str = '{} / {}'.format(models.MenuItem.format_price(menu_item.price_students),
                                     models.MenuItem.format_price(menu_item.price_staff))

    return '{} {} ({})'.format(models.food_type_icons[menu_item.food_type], translation_obj.translation, price_str)


def prepare_menu_text(campus: models.Campus, day: datetime.date, translator: translation.TranslationService,
                      locale: str) -> 'Optional[str]':
    menu = models.Menu.get_menu(campus, day)

    if menu is None:
        return None

    result = [localisation.REPLY_MENU_START(locale).format(campus=campus.short_name.upper(), date=str(day)), '']

    if len(menu.menu_items) < 6:
        result.insert(1, localisation.REPLY_MENU_INCOMPLETE(locale))

    try:
        for item in menu.menu_items:  # type: models.MenuItem
            result.append(get_menu_line(item, translator, locale))
    except Exception:
        print('Failed translating to {}'.format(locale), flush=True)
        raise

    return '\n'.join(result)
