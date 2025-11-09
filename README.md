# Stygian Relay

A powerful and customizable Discord bot for forwarding messages between channels with advanced filtering and logging capabilities. This bot is currently a work in progress.

## Current State

This bot is in active development. The core functionality of message forwarding, including message listening, rule processing, and message dispatching based on configured rules, is now implemented. A setup wizard guides you through the initial configuration. While the core forwarding is functional, some advanced features are still under development, and you may encounter bugs.

## Features

- **Cross-channel message forwarding:** Forward messages from one channel to another, even across different servers, based on detailed rules.
- **Advanced filtering:** Filter messages based on content, message type (text, media, links, embeds, files, stickers), and length. (Further advanced filtering like author/role is Work in Progress)
- **Customizable prefixes:** Set a custom command prefix for each server.
- **Database integration:** Per-guild settings are stored in a database.
- **Extensible:** The bot is designed to be easily extensible with new cogs and extensions.
- **Logging:** Comprehensive logging with email notifications for errors.
- **Welcome messages:** Greet new guilds with a customizable welcome message.
- **Auto-sharding:** The bot is designed to scale to a large number of guilds.

## Permissions Required

The bot requires the following permissions to function correctly. You will be prompted during the setup process if any of these are missing.

### Basic Permissions (Required)

- **View Channels:** To see the channels in your server and allow you to select them for forwarding.
- **Send Messages:** To send forwarded messages, welcome messages, and command responses.
- **Read Message History:** To read messages in the source channels that need to be forwarded.
- **Attach Files:** To forward messages that contain file attachments.
- **Embed Links:** To properly display embeds in forwarded messages.

### Advanced Permissions (Recommended)

- **Manage Webhooks:** For more seamless and customizable message forwarding, using webhooks allows the bot to send messages with a custom name and avatar.
- **Manage Messages:** To perform cleanup operations, such as deleting the original message after forwarding.
- **Add Reactions:** For interactive features and feedback.

### User Permissions

- **Manage Server:** The user who runs the `/setup` command must have the "Manage Server" permission.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/your-repository-name.git
   cd your-repository-name
   ```

2. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create a `.env` file in the root directory of the project and add the following:**
   ```
   DISCORD_TOKEN=your_discord_bot_token
   EMAIL=your_email@example.com
   PASSWORD=your_email_app_password
   BOT_OWNER_ID=your_discord_user_id
   ```

   - `DISCORD_TOKEN`: Your Discord bot token.
   - `EMAIL`: Your email address for error notifications.
   - `PASSWORD`: Your email app password (if using Gmail, you'll need to create an app password).
   - `BOT_OWNER_ID`: Your Discord user ID.

## Usage

To run the bot, execute the following command:

```bash
python main.py
```

### Setup

To start configuring the bot, use the `/setup` command. This will launch an interactive setup wizard that will guide you through the following steps:

1.  **Permission Check:** The bot will check if it has all the necessary permissions.
2.  **Log Channel:** You can set a channel where the bot will log errors and other important information.
3.  **First Forwarding Rule:** You will be guided through creating your first message forwarding rule, including selecting a source and destination channel.

## Dependencies

The project's dependencies are listed in the `requirements.txt` file.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.