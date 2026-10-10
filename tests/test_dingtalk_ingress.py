"""Authenticated stream carries stable platform event IDs and typed identity provenance."""
from unittest.mock import AsyncMock

import pytest

from echo_agent.channels.dingtalk import DingTalkChannel
from echo_agent.config.schema import DingTalkChannelConfig


# /***********************************************************
#  *                      本地方法                          *
#  ***********************************************************/

@pytest.mark.asyncio
async def test_stream_message_identity_is_stable_across_callback_replay():
    bus = AsyncMock()
    bus.publish_inbound.return_value = True
    channel = DingTalkChannel(DingTalkChannelConfig(), bus)
    payload = {'senderStaffId': 'staff', 'conversationType': '1', 'msgId': 'platform-message',
               'msgtype': 'text', 'text': {'content': '查看任务'}}
    await channel._on_message(payload)
    await channel._on_message(payload)
    first, second = [call.args[0] for call in bus.publish_inbound.call_args_list]
    assert first.event_id == second.event_id == 'platform-message'
    assert first.channel_verified is True and first.sender_id == 'staff'


@pytest.mark.asyncio
async def test_native_file_callback_preserves_name_and_identity_without_fetching_bytes():
    bus = AsyncMock()
    channel = DingTalkChannel(DingTalkChannelConfig(), bus)
    channel._resolve_download_code = AsyncMock(return_value='https://files.example/native-token')
    await channel._on_message({'senderStaffId': 'staff', 'conversationType': '2', 'conversationId': 'cid-group',
        'msgId': 'native-file-event', 'msgtype': 'file', 'content': {'fileName': '正文.docx', 'downloadCode': 'temporary-code'}})
    event = bus.publish_inbound.call_args.args[0]
    assert event.channel_verified and event.event_id == 'native-file-event'
    assert event.content[-1].metadata['name'] == '正文.docx'
    assert 'temporary-code' not in str(event)


@pytest.mark.asyncio
async def test_native_video_callback_uses_documented_type_and_stable_opaque_filename():
    bus = AsyncMock()
    channel = DingTalkChannel(DingTalkChannelConfig(), bus)
    channel._resolve_download_code = AsyncMock(return_value='https://files.example/native-token')
    body = {'senderStaffId': 'staff', 'conversationType': '1', 'msgId': 'native-video-event',
            'msgtype': 'video', 'content': {'videoType': 'mp4', 'duration': '5', 'downloadCode': 'temporary-code'}}
    await channel._on_message(body)
    await channel._on_message(body)
    events = [call.args[0] for call in bus.publish_inbound.call_args_list]
    assert len(events) == 2 and events[0].channel_verified
    assert events[0].content[-1].metadata['name'].endswith('.mp4')
    assert events[0].content[-1].metadata['name'] == events[1].content[-1].metadata['name']
    assert 'temporary-code' not in str(events[0])
