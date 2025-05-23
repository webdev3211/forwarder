
# @client.on(events.NewMessage(chats=source_channel))
# async def handler(event):
#     msg = event.message
#     text = msg.message or ""  # This is the caption (if any)
#     modified_text = modify_message(text)
#     print(msg)

#     for channel in destination_channels:
#         try:
#             # if msg.media:
#             #     # Send media + modified caption
#             #     await client.send_file(channel, file=msg.media, caption=modified_text)
#             # else:
#                 # Just send text
#             await client.send_message(channel, modified_text)

#             print(f"Sent to {channel}")
#         except Exception as e:
#             print(f"Failed to send to {channel}: {e}")


# async def main():
#     await client.start(phone=phone_number)
#     print("Listening for new messages from source channel...")
#     await client.run_until_disconnected()

# client.loop.run_until_complete(main())
