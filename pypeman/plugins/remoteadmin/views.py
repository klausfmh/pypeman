import json
import logging

from aiohttp import web
from jsonrpcserver.response import SuccessResponse

from pypeman import channels

logger = logging.getLogger(__name__)


def get_channel(name):
    """
    return channel by is name.all_channels
    """
    for chan in channels.all_channels:
        if chan.name == name:
            return chan
    return None


async def list_channels(request, ws=None):
    """
    Return a list of available channels.
    """
    if ws is None:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chans = []
    for chan in channels.all_channels:
        if not chan.parent:
            chan_dict = chan.to_dict()
            chan_dict['subchannels'] = chan.subchannels()

            chans.append(chan_dict)

    resp_message = json.dumps(chans)
    await ws.send_str(resp_message)


async def start_channel(request, channelname, ws=None):
    """
    Start the specified channel

    :params channel: The channel name to start.
    """
    if not ws:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chan = get_channel(channelname)
    await chan.start()

    resp_message = json.dumps({
        'name': chan.name,
        'status': channels.BaseChannel.status_id_to_str(chan.status)
    })
    await ws.send_str(resp_message)


async def stop_channel(request, channelname, ws=None):
    """
    Stop the specified channel

    :params channel: The channel name to stop.
    """
    if not ws:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chan = get_channel(channelname)
    await chan.stop()

    resp_message = json.dumps({
        'name': chan.name,
        'status': channels.BaseChannel.status_id_to_str(chan.status)
    })
    await ws.send_str(resp_message)


async def list_msgs(request, channelname, ws=None):
    """
    List first `count` messages from message store of specified channel.

    :params channel: The channel name.
    """
    if ws is None:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chan = get_channel(channelname)

    args = request.rel_url.query
    start = int(args.get("start", 0))
    count = int(args.get("count", 10))
    order_by = args.get("order_by", "timestamp")
    start_dt = args.get("start_dt", None)
    end_dt = args.get("end_dt", None)
    text = args.get("text", None)
    rtext = args.get("rtext", None)

    messages = await chan.message_store.search(
        start=start, count=count, order_by=order_by, start_dt=start_dt, end_dt=end_dt,
        text=text, rtext=rtext) or []

    for res in messages:
        res['timestamp'] = res['message'].timestamp_str()
        res['message'] = res['message'].to_json()

    resp_message = json.dumps({'messages': messages, 'total': await chan.message_store.total()})
    await ws.send_str(resp_message)


async def replay_msg(request, channelname, message_id, ws=None):
    """
    Replay messages from message store.

    :params channel: The channel name.
    :params msg_ids: The message ids list to replay.
    """
    if not ws:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chan = get_channel(channelname)
    result = []
    try:
        msg_res = await chan.replay(message_id)
        result.append(msg_res.to_dict())
    except Exception as exc:
        result.append({'error': str(exc)})

    resp_message = json.dumps(result)
    await ws.send_str(resp_message)


async def view_msg(request, channelname, message_id, ws=None):
    """
    Permit to get the content of a message

    :params channel: The channel name.
    :params msg_ids: The message ids list to replay.
    """
    if not ws:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chan = get_channel(channelname)
    result = []
    try:
        msg_res = await chan.message_store.get_msg_content(message_id)
        result.append(msg_res.to_dict())
    except Exception as exc:
        result.append({'error': str(exc)})

    resp_message = json.dumps(result)
    await ws.send_str(resp_message)


async def preview_msg(request, channelname, message_id, ws=None):
    """
    Permits to get the 1000 chars of a message payload

    :params channel: The channel name.
    :params msg_ids: The message ids list to replay.
    """
    if not ws:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

    chan = get_channel(channelname)
    result = []
    try:
        msg_res = await chan.message_store.get_preview_str(message_id)
        result.append(msg_res.to_dict())
    except Exception as exc:
        result.append({'error': str(exc)})

    resp_message = json.dumps(result)
    await ws.send_str(resp_message)


class RPCWebSocketResponse(web.WebSocketResponse):
    """
    Mocked aiohttp.web.WebSocketResponse to return JSOn RPC responses
    Workaround to have a backport compatibility with old json rpc client
    """

    def set_rpc_attrs(self, request_data):
        self.rpc_data = request_data

    async def send_str(self, message):
        message = SuccessResponse(json.loads(message), id=self.rpc_data["id"])
        await super().send_str(str(message))


async def backport_old_client(request):
    ws = RPCWebSocketResponse()
    await ws.prepare(request)
    async for msg in ws:
        try:
            cmd_data = json.loads(msg.data)
        except Exception:
            await ws.send_str(f"cannot parse ws json data ({msg.data})")
            return ws
        ws.set_rpc_attrs(cmd_data)
        cmd_method = cmd_data.pop("method")
        params = cmd_data.get("params", [None])
        channelname = params[0]

        if cmd_method == "channels":
            await list_channels(request, ws=ws)
        elif cmd_method == "preview_msg":
            message_id = params[1]
            await preview_msg(request, channelname=channelname, message_id=message_id, ws=ws)
        elif cmd_method == "view_msg":
            message_id = params[1]
            await view_msg(request=request, channelname=channelname, message_id=message_id, ws=ws)
        elif cmd_method == "replay_msg":
            message_id = params[1]
            await replay_msg(request=request, channelname=channelname, message_id=message_id, ws=ws)
        elif cmd_method == "list_msgs":
            query_params = {
                "start": params[1],
                "count": params[2],
                "order_by": params[3],
                "start_dt": params[4],
                "end_dt": params[5],
                "text": params[6],
                "rtext": params[7],
            }
            query_params = {k: v for k, v in query_params.items() if v is not None}
            request.rel_url.update_query(query_params)
            await list_msgs(request=request, channelname=channelname, ws=ws)
        elif cmd_method == "start_channel":
            await start_channel(request=request, channelname=channelname, ws=ws)
        elif cmd_method == "stop_channel":
            await stop_channel(request=request, channelname=channelname, ws=ws)
        else:
            await ws.send_str(f"{cmd_method} is not a valid method")
