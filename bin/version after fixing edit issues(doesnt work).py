import logging
import traceback

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes, CallbackQueryHandler
)

from app.config.settings import TELEGRAM_BOT_TOKEN
from app.db.database import SessionLocal
from app.crud.crud_user import create_user, get_user_by_telegram_id, update_user
from app.crud.crud_task import create_task, get_all_tasks, get_task_by_id
from app.crud.crud_reaction import create_reaction, check_mutual_like, create_match
from app.models.models import UserRole, ReactionType
from app.services.llm_service import categorize_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
ASK_ROLE, ASK_NAME, ASK_SKILLS = range(3)
ASK_TASK_DESC, ASK_TASK_TIMEFRAME, ASK_TASK_REWARD = range(3)

EDIT_FIELD, EDIT_VALUE = range(2)
CONFIRM_DELETE = range(1)

#####################
# Main Menu
#####################
main_menu_keyboard = [
    ["Help", "Profile"],
    ["Recommendations", "Show My Likes"]
]
main_menu_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True, one_time_keyboard=False)

#####################
# Inline Keyboards for Profile Management
#####################
def profile_inline_keyboard():
    buttons = [
        [InlineKeyboardButton("Edit Profile", callback_data="edit_profile"),
         InlineKeyboardButton("Save Profile", callback_data="save_profile")]
    ]
    return InlineKeyboardMarkup(buttons)

def edit_fields_inline_keyboard():
    buttons = [
        [InlineKeyboardButton("Name", callback_data="edit_name"),
         InlineKeyboardButton("Description", callback_data="edit_description")],
        [InlineKeyboardButton("University", callback_data="edit_university"),
         InlineKeyboardButton("Study Year", callback_data="edit_study_year")],
        [InlineKeyboardButton("Cancel Editing", callback_data="cancel_editing")]
    ]
    return InlineKeyboardMarkup(buttons)

#####################
# Utility Functions
#####################
def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    db.close()
    if not user:
        return update.message.reply_text("You are not registered. Use /register first.", reply_markup=main_menu_markup)

    msg = (f"Your Profile:\n"
           f"Name: {user.name}\n"
           f"Role: {user.role.value}\n"
           f"Description: {user.description or 'N/A'}\n"
           f"Categories: {user.categories or 'N/A'}\n"
           f"University: {user.university or 'N/A'}\n"
           f"Study Year: {user.study_year if user.study_year is not None else 'N/A'}")

    return update.message.reply_text(msg, reply_markup=profile_inline_keyboard())

async def show_profile_in_new_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    db.close()
    msg = (f"Your Profile:\n"
           f"Name: {user.name}\n"
           f"Role: {user.role.value}\n"
           f"Description: {user.description or 'N/A'}\n"
           f"Categories: {user.categories or 'N/A'}\n"
           f"University: {user.university or 'N/A'}\n"
           f"Study Year: {user.study_year if user.study_year is not None else 'N/A'}")
    await update.effective_message.reply_text(msg, reply_markup=profile_inline_keyboard())

#####################
# Global Handlers
#####################
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Innovedge Bot!\nUse /register to create your profile.",
        reply_markup=main_menu_markup
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation canceled.", reply_markup=main_menu_markup)
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("An error occurred: %s", context.error)
    logger.error("Traceback: %s", ''.join(traceback.format_exception(None, context.error, context.error.__traceback__)))
    if update and getattr(update, "message", None):
        await update.message.reply_text("An internal error occurred. Please try again later.", reply_markup=main_menu_markup)

#####################
# Registration Flow
#####################
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role_keyboard = [["TALENT", "EMPLOYER"]]
    await update.message.reply_text(
        "Are you registering as TALENT or EMPLOYER?",
        reply_markup=ReplyKeyboardMarkup(role_keyboard, one_time_keyboard=True)
    )
    return ASK_ROLE

async def received_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role_str = update.message.text.upper()
    if role_str not in ["TALENT", "EMPLOYER"]:
        await update.message.reply_text("Please choose TALENT or EMPLOYER.")
        return ASK_ROLE
    context.user_data["role"] = UserRole.TALENT if role_str == "TALENT" else UserRole.EMPLOYER
    await update.message.reply_text("Great, what's your name?", reply_markup=ReplyKeyboardRemove())
    return ASK_NAME

async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Name cannot be empty.")
        return ASK_NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        "Please describe your skill sets or expertise (e.g., 'I am good at web development and design').",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_SKILLS

async def received_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    skills_description = update.message.text.strip()
    telegram_user_id = update.message.from_user.id
    categories = categorize_text(skills_description)

    db = SessionLocal()
    new_user = create_user(
        db=db,
        telegram_id=telegram_user_id,
        name=context.user_data["name"],
        role=context.user_data["role"],
        description=skills_description,
        categories=categories if categories else None
    )
    db.close()

    await update.message.reply_text(
        f"Registered {new_user.name} as {new_user.role.value}! Categories: {new_user.categories or 'None'}",
        reply_markup=main_menu_markup
    )
    return ConversationHandler.END

register_conv = ConversationHandler(
    entry_points=[CommandHandler("register", register_command)],
    states={
        ASK_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_role)],
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name)],
        ASK_SKILLS: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_skills)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

#####################
# Post Task Flow (Employers)
#####################
async def post_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.message.from_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    db.close()
    if not user or user.role != UserRole.EMPLOYER:
        await update.message.reply_text("Only employers can post tasks.", reply_markup=main_menu_markup)
        return ConversationHandler.END

    await update.message.reply_text("Please provide a description of the task:", reply_markup=ReplyKeyboardRemove())
    return ASK_TASK_DESC

async def received_task_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_desc"] = update.message.text
    await update.message.reply_text("Got it. What's the timeframe for this task?")
    return ASK_TASK_TIMEFRAME

async def received_task_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_timeframe"] = update.message.text
    await update.message.reply_text("What is the reward for completing this task?")
    return ASK_TASK_REWARD

async def received_task_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_reward"] = update.message.text
    description = context.user_data["task_desc"]
    categories = categorize_text(description)

    telegram_user_id = update.message.from_user.id
    db = SessionLocal()
    employer_user = get_user_by_telegram_id(db, telegram_user_id)
    new_task = create_task(
        db=db,
        owner_id=employer_user.id,
        description=description,
        timeframe=context.user_data["task_timeframe"],
        reward=context.user_data["task_reward"],
        categories=categories if categories else None
    )
    db.close()

    await update.message.reply_text(
        f"Task posted successfully with ID {new_task.id}! Categories: {new_task.categories or 'None'}",
        reply_markup=main_menu_markup
    )
    return ConversationHandler.END

post_task_conv = ConversationHandler(
    entry_points=[CommandHandler("post_task", post_task_command)],
    states={
        ASK_TASK_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_task_desc)],
        ASK_TASK_TIMEFRAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_task_timeframe)],
        ASK_TASK_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_task_reward)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

#####################
# Profile and Editing Handlers
#####################
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    db.close()
    if not user:
        await update.message.reply_text("You are not registered. Use /register first.", reply_markup=main_menu_markup)
        return
    show_profile(update, context)

async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "edit_profile":
        await query.edit_message_reply_markup(reply_markup=edit_fields_inline_keyboard())
    elif query.data == "save_profile":
        await query.edit_message_text(text="Profile saved (no changes)!")
        await show_profile_in_new_message(update, context)

async def edit_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_editing":
        await query.edit_message_text("Editing canceled.")
        await show_profile_in_new_message(update, context)
        return ConversationHandler.END

    field_map = {
        "edit_name": "name",
        "edit_description": "description",
        "edit_university": "university",
        "edit_study_year": "study_year"
    }

    if query.data in field_map:
        context.user_data["editing_field"] = field_map[query.data]
        await query.edit_message_text(
            f"Enter new value for {field_map[query.data]}:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Editing", callback_data="cancel_editing")]])
        )
        return EDIT_VALUE

async def edit_profile_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_value = update.message.text.strip()
    field = context.user_data.get("editing_field")
    telegram_user_id = update.message.from_user.id
    db = SessionLocal()

    if field == "study_year":
        try:
            new_value = int(new_value)
        except ValueError:
            await update.message.reply_text("Study year must be a number, try again or cancel editing.",
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Editing", callback_data="cancel_editing")]]))
            return EDIT_VALUE

    updated_user = update_user(db, telegram_id=telegram_user_id, **{field: new_value})
    db.close()

    if updated_user:
        await update.message.reply_text(f"{field.capitalize()} updated successfully!", reply_markup=main_menu_markup)
    else:
        await update.message.reply_text("Could not update the profile. Please try again.", reply_markup=main_menu_markup)

    # Show updated profile again
    show_profile(update, context)
    return ConversationHandler.END

edit_profile_conv = ConversationHandler(
    entry_points=[],
    states={
        EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_profile_value)]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    map_to_parent={}
)

#####################
# Delete Profile
#####################
async def delete_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    db.close()
    if not user:
        await update.message.reply_text("You have no profile to delete.", reply_markup=main_menu_markup)
        return ConversationHandler.END

    await update.message.reply_text(
        "Are you sure you want to delete your profile? If yes, type exactly:\n\npapafranchesco is genius\n\nOtherwise, /cancel.",
        reply_markup=ReplyKeyboardRemove()
    )
    return CONFIRM_DELETE

async def confirm_delete_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "papafranchesco is genius":
        telegram_user_id = update.message.from_user.id
        db = SessionLocal()
        user = get_user_by_telegram_id(db, telegram_user_id)
        if user:
            db.delete(user)
            db.commit()
        db.close()
        await update.message.reply_text("Your profile has been deleted.", reply_markup=main_menu_markup)
    else:
        await update.message.reply_text("Profile deletion canceled or phrase not matched.", reply_markup=main_menu_markup)
    return ConversationHandler.END

delete_profile_conv = ConversationHandler(
    entry_points=[CommandHandler("delete_profile", delete_profile_command)],
    states={
        CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_profile)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

#####################
# Menu Command Handlers
#####################
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Help Menu:\n"
        "/register - Register as TALENT or EMPLOYER.\n"
        "/profile - View your profile and manage it.\n"
        "/browse_tasks - (If TALENT) Browse available tasks.\n"
        "/apply_task <task_id> - Apply to a specific task.\n"
        "/post_task - (If EMPLOYER) Post a new task.\n"
        "/delete_profile - Delete your profile (requires confirmation).\n\n"
        "Use the menu below for quick navigation."
    )
    await update.message.reply_text(help_text, reply_markup=main_menu_markup)

async def recommendations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Recommendations feature is coming soon!", reply_markup=main_menu_markup)

async def show_likes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Your likes: (This feature is under construction)", reply_markup=main_menu_markup)

#####################
# Browse & Apply Tasks (Talents)
#####################
async def browse_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    if not user or user.role != UserRole.TALENT:
        await update.message.reply_text("Only talents can browse tasks.", reply_markup=main_menu_markup)
        db.close()
        return

    tasks = get_all_tasks(db)
    db.close()
    if not tasks:
        await update.message.reply_text("No tasks available at the moment.", reply_markup=main_menu_markup)
        return

    msg = "Available Tasks:\n"
    for t in tasks:
        msg += f"ID: {t.id}, Desc: {t.description[:50]}..., Categories: {t.categories or 'N/A'}, Reward: {t.reward or 'N/A'}\n"
    await update.message.reply_text(msg, reply_markup=main_menu_markup)

async def apply_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.message.from_user.id
    db = SessionLocal()
    user = get_user_by_telegram_id(db, telegram_user_id)
    if not user or user.role != UserRole.TALENT:
        await update.message.reply_text("Only talents can apply to tasks.", reply_markup=main_menu_markup)
        db.close()
        return

    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text("Usage: /apply_task <task_id>", reply_markup=main_menu_markup)
        db.close()
        return
    try:
        task_id = int(parts[1])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.", reply_markup=main_menu_markup)
        db.close()
        return

    task = get_task_by_id(db, task_id)
    if not task:
        await update.message.reply_text("Task not found.", reply_markup=main_menu_markup)
        db.close()
        return

    create_reaction(db, from_user_id=user.id, to_user_id=task.owner_id, reaction_type=ReactionType.LIKE)
    if check_mutual_like(db, user.id, task.owner_id):
        create_match(db, user.id, task.owner_id)
        await update.message.reply_text("Applied successfully, and it's a match!", reply_markup=main_menu_markup)
        employer_user = db.query(task.owner.__class__).filter_by(id=task.owner_id).first()
        if employer_user:
            await context.bot.send_message(chat_id=employer_user.telegram_id, text="You have a new match!")
    else:
        await update.message.reply_text("Applied successfully!", reply_markup=main_menu_markup)

    db.close()

#####################
# Handle Menu Buttons as Messages
#####################
async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "help":
        await help_command(update, context)
    elif text == "profile":
        telegram_user_id = update.effective_user.id
        db = SessionLocal()
        user = get_user_by_telegram_id(db, telegram_user_id)
        db.close()
        if not user:
            await update.message.reply_text("You are not registered. Use /register first.", reply_markup=main_menu_markup)
        else:
            show_profile(update, context)
    elif text == "recommendations":
        await recommendations_command(update, context)
    elif text == "show my likes":
        await show_likes_command(update, context)
    else:
        await update.message.reply_text("Unrecognized option. Use the menu buttons or /help for assistance.",
                                        reply_markup=main_menu_markup)

#####################
# Main Function
#####################
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Error handler
    application.add_error_handler(error_handler)

    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(register_conv)
    application.add_handler(post_task_conv)
    application.add_handler(CommandHandler("browse_tasks", browse_tasks_command))
    application.add_handler(CommandHandler("apply_task", apply_task_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("recommendations", recommendations_command))
    application.add_handler(CommandHandler("show_likes", show_likes_command))
    application.add_handler(delete_profile_conv)

    # Add the edit_profile_conv BEFORE the menu text handler
    application.add_handler(edit_profile_conv)

    # CallbackQueryHandlers for profile editing
    application.add_handler(CallbackQueryHandler(profile_callback, pattern="^(edit_profile|save_profile)$"))
    application.add_handler(CallbackQueryHandler(edit_profile_callback, pattern="^(edit_name|edit_description|edit_university|edit_study_year|cancel_editing)$"))

    # The global menu text handler is added LAST to avoid interfering with conversation states
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons))

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
