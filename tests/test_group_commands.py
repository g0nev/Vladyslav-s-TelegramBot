import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject
from aiogram.types import ChatPermissions

from admin import group_commands
from db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


def make_message(user_id=1, chat_id=1, reply_to=None, photo=None):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type="group"),
        from_user=from_user,
        reply_to_message=reply_to,
        photo=photo,
        answer=AsyncMock(),
    )


def make_reply(message_id=999):
    return SimpleNamespace(message_id=message_id)


async def make_bot(is_admin_user_id=1):
    bot = AsyncMock()

    async def get_chat_member(chat_id, user_id):
        status = "administrator" if user_id == is_admin_user_id else "member"
        return SimpleNamespace(status=status)

    bot.get_chat_member.side_effect = get_chat_member
    return bot


def cmd(args):
    return CommandObject(prefix="/", command="x", args=args)


# --- /pin ---


async def test_pin_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    message = make_message(user_id=1, reply_to=make_reply())

    await group_commands.cmd_pin(message, bot)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )
    bot.pin_chat_message.assert_not_called()


async def test_pin_without_reply_shows_usage(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_pin(message, bot)

    message.answer.assert_awaited_once_with(
        "Ответьте этой командой на сообщение, которое нужно закрепить."
    )


async def test_pin_with_reply_pins_message(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1, reply_to=make_reply(message_id=42))

    await group_commands.cmd_pin(message, bot)

    bot.pin_chat_message.assert_awaited_once_with(1, message_id=42)
    message.answer.assert_awaited_once_with("Сообщение закреплено.")


async def test_pin_missing_rights_reports_error(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.pin_chat_message.side_effect = TelegramAPIError(method=None, message="no rights")
    message = make_message(user_id=1, reply_to=make_reply())

    await group_commands.cmd_pin(message, bot)

    message.answer.assert_awaited_once_with("Боту не хватает прав на закрепление сообщений.")


# --- /unpin ---


async def test_unpin_without_reply_unpins_latest(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_unpin(message, bot)

    bot.unpin_chat_message.assert_awaited_once_with(1)
    message.answer.assert_awaited_once_with("Сообщение откреплено.")


async def test_unpin_with_reply_unpins_specific(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1, reply_to=make_reply(message_id=7))

    await group_commands.cmd_unpin(message, bot)

    bot.unpin_chat_message.assert_awaited_once_with(1, message_id=7)


async def test_unpin_missing_rights_reports_unpin_specific_error(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.unpin_chat_message.side_effect = TelegramAPIError(method=None, message="no rights")
    message = make_message(user_id=1)

    await group_commands.cmd_unpin(message, bot)

    message.answer.assert_awaited_once_with("Боту не хватает прав на открепление сообщений.")


# --- /lock ---


async def test_lock_saves_permissions_and_locks(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.get_chat.return_value = SimpleNamespace(permissions=ChatPermissions(can_send_messages=True))
    message = make_message(user_id=1)

    await group_commands.cmd_lock(message, bot, repo)

    saved = await repo.get_saved_permissions(1)
    assert saved is not None
    assert json.loads(saved)["can_send_messages"] is True
    bot.set_chat_permissions.assert_awaited_once()
    _, kwargs = bot.set_chat_permissions.await_args
    assert kwargs["permissions"].can_send_messages is False
    message.answer.assert_awaited_once_with("Чат заблокирован — только админы могут писать.")


async def test_lock_does_not_overwrite_existing_saved_permissions(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.get_chat.return_value = SimpleNamespace(permissions=ChatPermissions(can_send_messages=True))
    await repo.set_saved_permissions(1, json.dumps({"can_send_messages": False}))
    message = make_message(user_id=1)

    await group_commands.cmd_lock(message, bot, repo)

    saved = await repo.get_saved_permissions(1)
    assert json.loads(saved)["can_send_messages"] is False
    bot.get_chat.assert_not_called()


async def test_lock_missing_rights_reports_error(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.get_chat.return_value = SimpleNamespace(permissions=ChatPermissions())
    bot.set_chat_permissions.side_effect = TelegramAPIError(method=None, message="no rights")
    message = make_message(user_id=1)

    await group_commands.cmd_lock(message, bot, repo)

    message.answer.assert_awaited_once_with("Боту не хватает прав на изменение прав чата.")


# --- /unlock ---


async def test_unlock_restores_saved_permissions(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_saved_permissions(1, json.dumps({"can_send_messages": True}))
    message = make_message(user_id=1)

    await group_commands.cmd_unlock(message, bot, repo)

    _, kwargs = bot.set_chat_permissions.await_args
    assert kwargs["permissions"].can_send_messages is True
    assert await repo.get_saved_permissions(1) is None
    message.answer.assert_awaited_once_with("Чат разблокирован.")


async def test_unlock_without_saved_permissions_uses_default(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_unlock(message, bot, repo)

    _, kwargs = bot.set_chat_permissions.await_args
    permissions = kwargs["permissions"]
    assert permissions.can_send_messages is True
    assert permissions.can_change_info is False
    assert permissions.can_invite_users is False
    assert permissions.can_pin_messages is False


# --- /newlink, /revokelink ---


async def test_newlink_creates_and_saves(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.create_chat_invite_link.return_value = SimpleNamespace(invite_link="https://t.me/+abc")
    message = make_message(user_id=1)

    await group_commands.cmd_newlink(message, bot, repo)

    assert await repo.get_last_invite_link(1) == "https://t.me/+abc"
    assert "https://t.me/+abc" in message.answer.await_args.args[0]


async def test_revokelink_without_prior_link(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_revokelink(message, bot, repo)

    message.answer.assert_awaited_once_with("Сначала создайте ссылку через /newlink.")
    bot.revoke_chat_invite_link.assert_not_called()


async def test_revokelink_revokes_and_clears(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_last_invite_link(1, "https://t.me/+abc")
    message = make_message(user_id=1)

    await group_commands.cmd_revokelink(message, bot, repo)

    bot.revoke_chat_invite_link.assert_awaited_once_with(1, invite_link="https://t.me/+abc")
    assert await repo.get_last_invite_link(1) is None
    message.answer.assert_awaited_once_with("Ссылка отозвана.")


# --- /chatinfo ---


async def test_chatinfo_reports_members_and_admins(repo):
    bot = AsyncMock()
    bot.get_chat_member_count.return_value = 42
    bot.get_chat_administrators.return_value = [
        SimpleNamespace(status="creator", user=SimpleNamespace(mention_html=lambda: "Owner")),
        SimpleNamespace(status="administrator", user=SimpleNamespace(mention_html=lambda: "Mod")),
    ]
    message = make_message(user_id=1)

    await group_commands.cmd_chatinfo(message, bot)

    text = message.answer.await_args.args[0]
    assert "42" in text
    assert "Owner" in text and "Mod" in text


# --- /settitle, /setdescription, /setphoto ---


async def test_settitle_rejects_empty(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_settitle(message, cmd(None), bot)

    message.answer.assert_awaited_once_with("Использование: /settitle «новое название»")
    bot.set_chat_title.assert_not_called()


async def test_settitle_updates(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_settitle(message, cmd("Новый чат"), bot)

    bot.set_chat_title.assert_awaited_once_with(1, "Новый чат")


async def test_setdescription_allows_empty(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_setdescription(message, cmd(None), bot)

    bot.set_chat_description.assert_awaited_once_with(1, "")


async def test_setphoto_without_photo_shows_usage(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await group_commands.cmd_setphoto(message, bot)

    message.answer.assert_awaited_once_with("Отправьте фото с подписью /setphoto.")
    bot.set_chat_photo.assert_not_called()


async def test_setphoto_with_photo_updates(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.download.return_value = io.BytesIO(b"fake-image-bytes")
    photo = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")]
    message = make_message(user_id=1, photo=photo)

    await group_commands.cmd_setphoto(message, bot)

    bot.download.assert_awaited_once_with("large")
    bot.set_chat_photo.assert_awaited_once()
    message.answer.assert_awaited_once_with("Фото чата обновлено.")


async def test_setphoto_download_failure_reports_no_rights(repo):
    bot = await make_bot(is_admin_user_id=1)
    bot.download.side_effect = TelegramAPIError(method=None, message="no rights")
    photo = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")]
    message = make_message(user_id=1, photo=photo)

    await group_commands.cmd_setphoto(message, bot)

    message.answer.assert_awaited_once_with("Боту не хватает прав на изменение фото чата.")
    bot.set_chat_photo.assert_not_called()


# --- join requests ---


async def test_join_request_sends_approval_prompt():
    bot = AsyncMock()
    request = SimpleNamespace(
        chat=SimpleNamespace(id=1),
        from_user=SimpleNamespace(id=200, mention_html=lambda: "Newcomer"),
    )

    await group_commands.on_join_request(request, bot)

    bot.send_message.assert_awaited_once()
    args, kwargs = bot.send_message.await_args
    assert args[0] == 1
    assert "Newcomer" in args[1]
    assert kwargs["reply_markup"] is not None


def make_callback(data, user_id=1, chat_id=1):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id), edit_text=AsyncMock()),
        answer=AsyncMock(),
    )


async def test_join_request_decision_by_non_admin_is_rejected():
    bot = AsyncMock()
    callback = make_callback("joinreq:200:approve", user_id=999)

    with patch("admin.group_commands.is_admin", AsyncMock(return_value=False)):
        await group_commands.on_join_request_decision(callback, bot)

    callback.answer.assert_awaited_once_with("Только админ может это решить.", show_alert=True)
    bot.approve_chat_join_request.assert_not_called()


async def test_join_request_decision_approve(repo):
    bot = AsyncMock()
    callback = make_callback("joinreq:200:approve", user_id=1)

    with patch("admin.group_commands.is_admin", AsyncMock(return_value=True)):
        await group_commands.on_join_request_decision(callback, bot)

    bot.approve_chat_join_request.assert_awaited_once_with(1, 200)
    callback.message.edit_text.assert_awaited_once_with("Заявка одобрена.")


async def test_join_request_decision_decline(repo):
    bot = AsyncMock()
    callback = make_callback("joinreq:200:decline", user_id=1)

    with patch("admin.group_commands.is_admin", AsyncMock(return_value=True)):
        await group_commands.on_join_request_decision(callback, bot)

    bot.decline_chat_join_request.assert_awaited_once_with(1, 200)
    callback.message.edit_text.assert_awaited_once_with("Заявка отклонена.")


async def test_join_request_decision_with_inaccessible_message_does_not_crash():
    bot = AsyncMock()
    callback = SimpleNamespace(
        data="joinreq:200:approve",
        from_user=SimpleNamespace(id=1),
        message=None,
        answer=AsyncMock(),
    )

    await group_commands.on_join_request_decision(callback, bot)

    callback.answer.assert_awaited_once_with(
        "Это сообщение о заявке больше не доступно.", show_alert=True
    )
    bot.approve_chat_join_request.assert_not_called()
