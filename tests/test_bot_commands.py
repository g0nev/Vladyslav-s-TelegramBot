from unittest.mock import AsyncMock

from aiogram.types import MenuButtonCommands

from admin.bot_commands import BOT_COMMANDS, register_commands


def test_bot_commands_cover_all_commands():
    names = {command.command for command in BOT_COMMANDS}
    assert names == {
        "addword",
        "delword",
        "listwords",
        "warns",
        "resetwarns",
        "setresetdays",
        "setinterval",
        "addmsg",
        "delmsg",
        "listmsgs",
        "setwarnmsg",
        "setmutemsg",
        "setkickmsg",
        "resetmsgs",
        "ask",
    }


async def test_register_commands_calls_set_my_commands():
    bot = AsyncMock()

    await register_commands(bot)

    bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)


async def test_register_commands_sets_menu_button():
    bot = AsyncMock()

    await register_commands(bot)

    bot.set_chat_menu_button.assert_awaited_once()
    _, kwargs = bot.set_chat_menu_button.await_args
    assert isinstance(kwargs["menu_button"], MenuButtonCommands)
