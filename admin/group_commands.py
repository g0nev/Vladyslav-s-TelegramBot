from __future__ import annotations

import html
import json

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ChatJoinRequest,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from admin.permissions import is_admin
from admin.permissions import require_admin as _require_admin
from db.repository import Repository

router = Router(name="group")

NO_RIGHTS_PIN = "Боту не хватает прав на закрепление сообщений."
NO_RIGHTS_UNPIN = "Боту не хватает прав на открепление сообщений."
EXPIRED_JOIN_REQUEST_MESSAGE = "Это сообщение о заявке больше не доступно."
ADMIN_RESERVED_PERMISSIONS = {"can_change_info", "can_invite_users", "can_pin_messages"}


def _all_permissions(value: bool) -> ChatPermissions:
    return ChatPermissions(**{field: value for field in ChatPermissions.model_fields})


def _default_unlocked_permissions() -> ChatPermissions:
    fields = {
        field: (False if field in ADMIN_RESERVED_PERMISSIONS else True)
        for field in ChatPermissions.model_fields
    }
    return ChatPermissions(**fields)


@router.message(Command("pin"))
async def cmd_pin(message: Message, bot: Bot) -> None:
    if not await _require_admin(message, bot):
        return
    if message.reply_to_message is None:
        await message.answer("Ответьте этой командой на сообщение, которое нужно закрепить.")
        return
    try:
        await bot.pin_chat_message(message.chat.id, message_id=message.reply_to_message.message_id)
    except TelegramAPIError:
        await message.answer(NO_RIGHTS_PIN)
        return
    await message.answer("Сообщение закреплено.")


@router.message(Command("unpin"))
async def cmd_unpin(message: Message, bot: Bot) -> None:
    if not await _require_admin(message, bot):
        return
    try:
        if message.reply_to_message is not None:
            await bot.unpin_chat_message(
                message.chat.id, message_id=message.reply_to_message.message_id
            )
        else:
            await bot.unpin_chat_message(message.chat.id)
    except TelegramAPIError:
        await message.answer(NO_RIGHTS_UNPIN)
        return
    await message.answer("Сообщение откреплено.")


@router.message(Command("lock"))
async def cmd_lock(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    try:
        already_saved = await repository.get_saved_permissions(message.chat.id)
        if already_saved is None:
            chat = await bot.get_chat(message.chat.id)
            current = chat.permissions or _default_unlocked_permissions()
            await repository.set_saved_permissions(
                message.chat.id, json.dumps(current.model_dump())
            )
        await bot.set_chat_permissions(message.chat.id, permissions=_all_permissions(False))
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на изменение прав чата.")
        return
    await message.answer("Чат заблокирован — только админы могут писать.")


@router.message(Command("unlock"))
async def cmd_unlock(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    saved = await repository.get_saved_permissions(message.chat.id)
    permissions = ChatPermissions(**json.loads(saved)) if saved else _default_unlocked_permissions()
    try:
        await bot.set_chat_permissions(message.chat.id, permissions=permissions)
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на изменение прав чата.")
        return
    await repository.set_saved_permissions(message.chat.id, None)
    await message.answer("Чат разблокирован.")


@router.message(Command("newlink"))
async def cmd_newlink(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    try:
        link = await bot.create_chat_invite_link(message.chat.id)
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на создание инвайт-ссылок.")
        return
    await repository.set_last_invite_link(message.chat.id, link.invite_link)
    await message.answer(f"Новая инвайт-ссылка: {link.invite_link}")


@router.message(Command("revokelink"))
async def cmd_revokelink(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    last_link = await repository.get_last_invite_link(message.chat.id)
    if not last_link:
        await message.answer("Сначала создайте ссылку через /newlink.")
        return
    try:
        await bot.revoke_chat_invite_link(message.chat.id, invite_link=last_link)
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на отзыв инвайт-ссылок.")
        return
    await repository.set_last_invite_link(message.chat.id, None)
    await message.answer("Ссылка отозвана.")


@router.message(Command("chatinfo"))
async def cmd_chatinfo(message: Message, bot: Bot) -> None:
    try:
        count = await bot.get_chat_member_count(message.chat.id)
        admins = await bot.get_chat_administrators(message.chat.id)
    except TelegramAPIError:
        await message.answer("Не удалось получить информацию о чате.")
        return
    lines = [f"Участников: {count}", "", "Админы:"]
    for admin in admins:
        role = "создатель" if admin.status == "creator" else "админ"
        lines.append(f"— {admin.user.mention_html()} ({role})")
    await message.answer("\n".join(lines))


@router.message(Command("settitle"))
async def cmd_settitle(message: Message, command: CommandObject, bot: Bot) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip():
        await message.answer("Использование: /settitle «новое название»")
        return
    title = command.args.strip()
    try:
        await bot.set_chat_title(message.chat.id, title)
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на изменение названия чата.")
        return
    await message.answer(f"Название чата изменено на «{html.escape(title)}».")


@router.message(Command("setdescription"))
async def cmd_setdescription(message: Message, command: CommandObject, bot: Bot) -> None:
    if not await _require_admin(message, bot):
        return
    description = command.args if command.args is not None else ""
    try:
        await bot.set_chat_description(message.chat.id, description)
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на изменение описания чата.")
        return
    await message.answer("Описание чата обновлено.")


@router.message(Command("setphoto"))
async def cmd_setphoto(message: Message, bot: Bot) -> None:
    if not await _require_admin(message, bot):
        return
    if not message.photo:
        await message.answer("Отправьте фото с подписью /setphoto.")
        return
    largest = message.photo[-1]
    try:
        file = await bot.download(largest.file_id)
        await bot.set_chat_photo(
            message.chat.id, photo=BufferedInputFile(file.read(), filename="chat_photo.jpg")
        )
    except TelegramAPIError:
        await message.answer("Боту не хватает прав на изменение фото чата.")
        return
    await message.answer("Фото чата обновлено.")


@router.chat_join_request()
async def on_join_request(request: ChatJoinRequest, bot: Bot) -> None:
    mention = request.from_user.mention_html()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=f"joinreq:{request.from_user.id}:approve"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"joinreq:{request.from_user.id}:decline"
                ),
            ]
        ]
    )
    await bot.send_message(
        request.chat.id,
        f"{mention} хочет вступить в чат. Одобрить заявку?",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("joinreq:"))
async def on_join_request_decision(callback: CallbackQuery, bot: Bot) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, user_id_raw, decision = parts
    user_id = int(user_id_raw)

    if callback.message is None:
        await callback.answer(EXPIRED_JOIN_REQUEST_MESSAGE, show_alert=True)
        return

    if callback.from_user is None or not await is_admin(
        bot, callback.message.chat.id, callback.from_user.id
    ):
        await callback.answer("Только админ может это решить.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    try:
        if decision == "approve":
            await bot.approve_chat_join_request(chat_id, user_id)
            result_text = "Заявка одобрена."
        else:
            await bot.decline_chat_join_request(chat_id, user_id)
            result_text = "Заявка отклонена."
    except TelegramAPIError:
        result_text = "Не удалось обработать заявку (возможно, она уже неактуальна)."

    await callback.message.edit_text(result_text)
    await callback.answer()
