from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
import random
import json
import os
import re


# 数据类定义
class Player:
    """玩家类"""
    def __init__(self, user_id, user_name):
        self.user_id = user_id
        self.user_name = user_name
        self.is_alive = True
        self.role = None  # citizen, undercover, whiteboard
        self.word = None
        self.last_speech = ""  # 本轮发言内容


class GameRoom:
    """游戏房间类"""
    def __init__(self, room_id, owner_id, owner_name):
        self.room_id = room_id
        self.owner_id = owner_id
        self.owner_name = owner_name
        self.players = []  # Player对象列表
        self.status = "waiting"  # waiting, playing, ended
        self.speech_order = []  # 发言顺序，仅包含存活玩家
        self.current_speaker_index = 0  # 当前发言玩家在 speech_order 中的索引
        self.votes = {}  # user_id: voted_user_id
        self.round = 1  # 当前轮次
        self.group_session_str = ""  # 群聊 session，用于向群内广播投票进度和结果
        self.whiteboard_guessing = False  # 白板被票后猜词阶段
        self.whiteboard_player = None  # 正在猜词的白板玩家
        self.citizen_word = ""  # 平民词，供白板猜词验证


# 主插件类
@register("undercover", "YourName", "谁是卧底游戏插件", "1.3.0")
class UndercoverPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.game_rooms = {}  # room_id: GameRoom对象
        self.user_rooms = {}  # user_id: room_id，记录用户所在房间
        self.word_pairs_file = "word_pairs.json"  # 词语库文件
        self.word_pairs = self.load_word_pairs()  # 加载词语库
        self.room_counter = 1  # 房间ID计数器

    async def initialize(self):
        """插件初始化"""
        logger.info("谁是卧底插件初始化成功")

    @filter.command_group("uc")
    def uc(self):
        pass

    @uc.command("help")
    async def uc_help(self, event: AstrMessageEvent):
        help_text = (
            "谁是卧底游戏指令：\n"
            "/uc help - 查看帮助\n"
            "/uc create - 创建游戏房间\n"
            "/uc join <房间号> - 加入游戏房间\n"
            "/uc start - 开始游戏（房主）\n"
            "/uc leave - 离开当前房间\n"
            "/uc say <内容> - 游戏中发言\n"
            "/uc vote <玩家> - 游戏中投票\n"
            "/uc guess <词语> - 白板猜词\n"
            "/uc end - 结束游戏（房主）\n"
            "/uc add <词语1> <词语2> - 添加词语对\n"
            "/uc word - 查看我的词语(请私聊使用)\n"
            "/uc list - 查看游戏列表\n"
        )
        yield event.plain_result(help_text)

    @uc.command("create")
    async def create_game(self, event: AstrMessageEvent):
        """创建游戏房间"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        if user_id in self.user_rooms:
            yield event.plain_result("你已在其他游戏房间中，请先离开")
            return

        room_id = str(self.room_counter)
        self.room_counter += 1

        game_room = GameRoom(room_id, user_id, user_name)
        self.game_rooms[room_id] = game_room

        player = Player(user_id, user_name)
        game_room.players.append(player)
        self.user_rooms[user_id] = room_id

        yield event.plain_result(f"游戏房间创建成功！房间号：{room_id}\n"
                                f"房主：{user_name}\n"
                                f"使用 /uc join {room_id} 邀请其他玩家加入")

    @uc.command("join")
    async def join_game(self, event: AstrMessageEvent, room_id: str = ""):
        """加入游戏房间"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        if not room_id:
            yield event.plain_result("请输入房间号，格式：/uc join <房间号>")
            return

        if room_id not in self.game_rooms:
            yield event.plain_result("房间不存在，请检查房间号")
            return

        game_room = self.game_rooms[room_id]

        if game_room.status != "waiting":
            yield event.plain_result("该房间游戏已开始，无法加入")
            return

        if user_id in self.user_rooms and self.user_rooms[user_id] == room_id:
            yield event.plain_result("你已在该房间中")
            return

        if user_id in self.user_rooms:
            yield event.plain_result("你已在其他游戏房间中，请先离开")
            return

        player = Player(user_id, user_name)
        game_room.players.append(player)
        self.user_rooms[user_id] = room_id

        yield event.plain_result(f"玩家 {user_name} 加入了游戏房间 {room_id}，当前人数：{len(game_room.players)}")

    @uc.command("start")
    async def start_game(self, event: AstrMessageEvent):
        """开始游戏"""
        user_id = event.get_sender_id()

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if game_room.owner_id != user_id:
            yield event.plain_result("只有房主可以开始游戏")
            return

        if game_room.status != "waiting":
            yield event.plain_result("游戏已开始")
            return

        if len(game_room.players) < 3:
            yield event.plain_result("玩家数量不足，至少需要3人")
            return

        game_room.status = "playing"

        # 随机选择一组词语，并随机决定哪边是卧底词
        word_pair = random.choice(self.word_pairs)
        if random.random() < 0.5:
            citizen_word, undercover_word = word_pair
        else:
            undercover_word, citizen_word = word_pair

        num_players = len(game_room.players)
        # 卧底数量：8人及以下1个卧底，8人以上2个卧底
        if num_players <= 8:
            num_undercover = 1
        else:
            num_undercover = 2

        # 随机打乱玩家顺序并分配身份
        random.shuffle(game_room.players)

        for i, player in enumerate(game_room.players):
            if i < num_undercover:
                player.role = "undercover"
                player.word = undercover_word
            else:
                player.role = "citizen"
                player.word = citizen_word

        # 5人及以上必定有一个白板（无词语），从平民中随机抽一个
        if num_players >= 5:
            whiteboard_candidates = [p for p in game_room.players if p.role == "citizen"]
            if whiteboard_candidates:
                wb = random.choice(whiteboard_candidates)
                wb.role = "whiteboard"
                wb.word = ""

        game_room.citizen_word = citizen_word

        # 建立发言顺序（仅存活玩家），5人以上卧底不排第一位
        game_room.speech_order = [p for p in game_room.players if p.is_alive]
        random.shuffle(game_room.speech_order)
        if len(game_room.speech_order) >= 5 and game_room.speech_order[0].role == "undercover":
            # 把卧底换到后面去
            swap_idx = random.randrange(1, len(game_room.speech_order))
            game_room.speech_order[0], game_room.speech_order[swap_idx] = \
                game_room.speech_order[swap_idx], game_room.speech_order[0]
        game_room.current_speaker_index = 0
        game_room.votes.clear()
        game_room.round = 1
        game_room.group_session_str = event.unified_msg_origin

        total_alive = len(game_room.speech_order)

        # 主动私聊每位玩家告知词语
        platform_id = event.get_platform_id()
        failed_players = []
        for player in game_room.players:
            try:
                private_session = MessageSession(
                    platform_name=platform_id,
                    message_type=MessageType.FRIEND_MESSAGE,
                    session_id=player.user_id,
                )
                if player.role == "whiteboard":
                    await self.context.send_message(
                        private_session,
                        MessageEventResult().message(
                            f"🎮 谁是卧底 游戏开始！\n"
                            f"📝 你是【白板】，没有词语！\n"
                            f"💡 请根据其他人的描述推测词语，在发言环节即兴发挥。\n"
                            f"💡 如果你被票出局，将获得一次猜词机会，猜对即可获胜！"
                        ),
                    )
                else:
                    await self.context.send_message(
                        private_session,
                        MessageEventResult().message(
                            f"🎮 谁是卧底 游戏开始！\n"
                            f"📝 你的词语是：{player.word}\n\n"
                            f"💡 请勿泄露你的词语！在发言环节描述它，让同伴找到你，让对手猜不到你。"
                        ),
                    )
            except Exception:
                failed_players.append(player.user_name)

        # 群聊公告
        if failed_players:
            failed_list = "、".join(failed_players)
            tip = f"\n⚠️ 以下玩家可能未收到私聊，请手动发送 /uc word 查看词语：{failed_list}"
        else:
            tip = ""

        yield event.plain_result(
            f"🎮 游戏开始！\n"
            f"🔢 卧底数量：{num_undercover}\n"
            f"👥 发言顺序：{' → '.join(p.user_name for p in game_room.speech_order)}\n"
            f"📨 词语和身份已私聊发送给各位玩家{tip}"
        )

        # 宣布第一位发言玩家（带 @）
        current_player = game_room.speech_order[0]
        yield MessageEventResult().at(current_player.user_name, current_player.user_id).message(
            f" 第 {game_room.round} 轮发言开始！请使用 /uc say <内容> 发言（发言次序 1/{total_alive}）"
        )

    @uc.command("leave")
    async def leave_game(self, event: AstrMessageEvent):
        """离开游戏房间"""
        user_id = event.get_sender_id()

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]
        user_name = event.get_sender_name()

        # 从 players 和 speech_order 中移除
        game_room.players = [p for p in game_room.players if p.user_id != user_id]
        game_room.speech_order = [p for p in game_room.speech_order if p.user_id != user_id]
        del self.user_rooms[user_id]

        if game_room.owner_id == user_id:
            if game_room.players:
                new_owner = game_room.players[0]
                game_room.owner_id = new_owner.user_id
                game_room.owner_name = new_owner.user_name
                yield event.plain_result(f"房主 {user_name} 已离开，新房主：{new_owner.user_name}")
            else:
                del self.game_rooms[room_id]
                yield event.plain_result("你已离开游戏房间，房间已解散")
                return
        else:
            yield event.plain_result(f"玩家 {user_name} 已离开游戏")

        yield event.plain_result("你已离开游戏房间")

    @uc.command("say")
    async def say(self, event: AstrMessageEvent):
        """游戏中发言"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        # 从原始消息中提取发言内容（避免 *args 参数解析兼容性问题）
        raw_msg = event.get_message_str()
        m = re.match(r'\S+\s+say\s+(.+)', raw_msg, re.IGNORECASE)
        text = m.group(1).strip() if m else ""

        if not text:
            yield event.plain_result("发言内容不能为空，请使用 /uc say <内容>")
            return

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if game_room.status != "playing":
            yield event.plain_result("游戏未开始")
            return

        # 确保 speech_order 只包含存活玩家（防御性清理）
        game_room.speech_order = [p for p in game_room.speech_order if p.is_alive]

        total_alive = len(game_room.speech_order)

        if game_room.current_speaker_index >= total_alive:
            yield event.plain_result("当前发言环节已结束，请使用 /uc vote <玩家> 进行投票")
            return

        # 获取当前应该发言的玩家
        current_player = game_room.speech_order[game_room.current_speaker_index]

        if current_player.user_id != user_id:
            yield MessageEventResult().at(current_player.user_name, current_player.user_id).message(
                f" 当前是你的发言轮次，请使用 /uc say <内容> 发言"
            )
            return

        player = next((p for p in game_room.players if p.user_id == user_id), None)
        if not player:
            yield event.plain_result("未找到玩家信息")
            return

        if not player.is_alive:
            yield event.plain_result("你已被淘汰，无法发言")
            return

        # 保存发言内容并推进索引
        player.last_speech = text
        game_room.current_speaker_index += 1
        spoken_count = game_room.current_speaker_index  # 已发言的存活玩家数

        # 发言确认（合并内容广播和进度）
        yield event.plain_result(f"💬 {user_name}：{text}\n✅ 发言已记录，当前发言次序({spoken_count}/{total_alive})")

        # 检查是否所有存活玩家都已发言
        if game_room.current_speaker_index >= total_alive:
            # 发言环节结束，进入投票环节
            game_room.votes.clear()
            speech_summary = "\n".join(
                f"  {p.user_name}：{p.last_speech}" for p in game_room.speech_order
            )
            yield event.plain_result(
                f"🎯 第 {game_room.round} 轮发言结束！\n"
                f"📋 本轮描述：\n{speech_summary}\n"
                f"🗳️ 请使用 /uc vote <玩家> 投票（私聊或群聊均可）"
            )
        else:
            # 提醒下一位玩家发言（带 @）
            next_player = game_room.speech_order[game_room.current_speaker_index]
            next_index = game_room.current_speaker_index + 1
            yield MessageEventResult().at(next_player.user_name, next_player.user_id).message(
                f" 请使用 /uc say <内容> 发言（发言次序 {next_index}/{total_alive}）"
            )

    @uc.command("vote")
    async def vote(self, event: AstrMessageEvent, target_name: str = ""):
        """游戏中投票（支持群聊和私聊）"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if game_room.status != "playing":
            yield event.plain_result("游戏未开始")
            return

        # 确保 speech_order 只包含存活玩家
        game_room.speech_order = [p for p in game_room.speech_order if p.is_alive]

        if game_room.current_speaker_index < len(game_room.speech_order):
            yield event.plain_result("当前仍在发言环节，无法投票")
            return

        if user_id in game_room.votes:
            yield event.plain_result("你已经投过票了")
            return

        voter = next((p for p in game_room.players if p.user_id == user_id), None)
        if not voter or not voter.is_alive:
            yield event.plain_result("你已被淘汰，无法投票")
            return

        if target_name.strip() == "弃权":
            game_room.votes[user_id] = None  # None 表示弃权
        else:
            target_player = None
            for p in game_room.players:
                if p.is_alive and target_name in p.user_name:
                    target_player = p
                    break

            if not target_player:
                yield event.plain_result(f"未找到存活玩家：{target_name}")
                return

            if target_player.user_id == user_id:
                yield event.plain_result("你不能投票给自己")
                return

            game_room.votes[user_id] = target_player.user_id

        alive_players = [p for p in game_room.players if p.is_alive]
        voted_count = len(game_room.votes)
        total_count = len(alive_players)

        # 向群聊发送投票进度（不透露谁投了谁）
        progress_msg = f"🗳️ 已投票 {voted_count}/{total_count}"
        await self._send_to_group(game_room, progress_msg)

        # 给投票者确认
        yield event.plain_result("✅ 你的投票已记录")

        # 检查是否所有存活玩家都已投票
        if voted_count >= total_count:
            # 统计投票结果
            vote_counts = {}
            for voted_id in game_room.votes.values():
                if voted_id is not None:  # 跳过弃权票
                    vote_counts[voted_id] = vote_counts.get(voted_id, 0) + 1

            if not vote_counts:
                # 全部弃权，无人被票出
                await self._send_to_group(game_room, "⚖️ 本轮全部弃权，无人被票出局！")
                game_room.round += 1
                game_room.speech_order = [p for p in game_room.players if p.is_alive]
                random.shuffle(game_room.speech_order)
                if len(game_room.speech_order) >= 5 and game_room.speech_order[0].role == "undercover":
                    swap_idx = random.randrange(1, len(game_room.speech_order))
                    game_room.speech_order[0], game_room.speech_order[swap_idx] = \
                        game_room.speech_order[swap_idx], game_room.speech_order[0]
                game_room.current_speaker_index = 0
                game_room.votes.clear()
                total_alive = len(game_room.speech_order)
                current_player = game_room.speech_order[0]
                yield MessageEventResult().at(current_player.user_name, current_player.user_id).message(
                    f" 第 {game_room.round} 轮发言开始！请使用 /uc say <内容> 发言（发言次序 1/{total_alive}）"
                )
                return

            max_votes = max(vote_counts.values())
            eliminated_players = [p for p in alive_players if vote_counts.get(p.user_id, 0) == max_votes]

            if len(eliminated_players) == 1:
                eliminated = eliminated_players[0]

                # 白板被票：进入猜词阶段
                if eliminated.role == "whiteboard":
                    eliminated.is_alive = False
                    game_room.whiteboard_guessing = True
                    game_room.whiteboard_player = eliminated
                    await self._send_to_group(game_room,
                        f"🗳️ 投票结果：\n玩家 {eliminated.user_name} 被票出局，身份是【白板】！\n"
                        f"💡 {eliminated.user_name} 获得一次猜词机会，请私聊使用 /uc guess <词语> 猜词！"
                    )
                    try:
                        private_session = MessageSession(
                            platform_name=event.get_platform_id(),
                            message_type=MessageType.FRIEND_MESSAGE,
                            session_id=eliminated.user_id,
                        )
                        await self.context.send_message(
                            private_session,
                            MessageEventResult().message(
                                f"你被票出局了，但作为【白板】获得一次猜词机会！\n"
                                f"请使用 /uc guess <词语> 猜词，猜对即可获胜！"
                            ),
                        )
                    except Exception:
                        pass
                    return

                eliminated.is_alive = False

                result_msg = f"🗳️ 投票结果：\n玩家 {eliminated.user_name} 被票出局！"
                await self._send_to_group(game_room, result_msg)

                # 检查游戏是否结束
                winner = self._check_winner(game_room)
                if winner:
                    player_list_str = "\n".join([
                        f"{p.user_name}：{'卧底' if p.role == 'undercover' else '白板' if p.role == 'whiteboard' else '平民'} - {p.word or '(无)'}"
                        for p in game_room.players
                    ])
                    await self._send_to_group(game_room, f"🏆 游戏结束！{winner}胜利！\n\n全员身份公示：\n{player_list_str}")
                    game_room.status = "ended"
                    return

                # 开始新一轮
                game_room.round += 1
                game_room.speech_order = [p for p in game_room.players if p.is_alive]
                random.shuffle(game_room.speech_order)
                if len(game_room.speech_order) >= 5 and game_room.speech_order[0].role == "undercover":
                    swap_idx = random.randrange(1, len(game_room.speech_order))
                    game_room.speech_order[0], game_room.speech_order[swap_idx] = \
                        game_room.speech_order[swap_idx], game_room.speech_order[0]
                game_room.current_speaker_index = 0
                game_room.votes.clear()

                total_alive = len(game_room.speech_order)
                await self._send_to_group(game_room,
                    f"🔄 第 {game_room.round} 轮开始！\n"
                    f"📋 存活玩家({total_alive}人)：{', '.join(p.user_name for p in game_room.speech_order)}"
                )

                # 提醒第一位发言玩家（带 @）
                current_player = game_room.speech_order[0]
                yield MessageEventResult().at(current_player.user_name, current_player.user_id).message(
                    f" 请使用 /uc say <内容> 发言（发言次序 1/{total_alive}）"
                )
            else:
                # 平票
                await self._send_to_group(game_room,
                    f"⚖️ 投票结果平票：{', '.join(p.user_name for p in eliminated_players)}\n"
                    "请重新投票！"
                )
                game_room.votes.clear()

    async def _send_to_group(self, game_room: GameRoom, message: str):
        """向群聊发送消息"""
        if game_room.group_session_str:
            try:
                await self.context.send_message(
                    game_room.group_session_str,
                    MessageEventResult().message(message),
                )
            except Exception:
                pass

    @uc.command("guess")
    async def guess_word(self, event: AstrMessageEvent):
        """白板猜词"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        # 从原始消息中提取猜词内容
        raw_msg = event.get_message_str()
        m = re.match(r'\S+\s+guess\s+(.+)', raw_msg, re.IGNORECASE)
        guess = m.group(1).strip() if m else ""

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if not game_room.whiteboard_guessing:
            yield event.plain_result("当前没有猜词机会")
            return

        if game_room.whiteboard_player.user_id != user_id:
            yield event.plain_result("只有被票出的白板可以猜词")
            return

        if not guess:
            yield event.plain_result("请使用 /uc guess <词语> 猜词")
            return

        game_room.whiteboard_guessing = False
        game_room.whiteboard_player = None

        if guess == game_room.citizen_word:
            # 猜对了！白板获胜
            player_list_str = "\n".join([
                f"{p.user_name}：{'卧底' if p.role == 'undercover' else '平民' if p.role == 'citizen' else '白板'} - {p.word or '(无)'}"
                for p in game_room.players
            ])
            await self._send_to_group(game_room,
                f"🎉 {user_name} 猜词正确！词语是：{game_room.citizen_word}\n"
                f"🏆 【白板】{user_name} 获胜！\n\n"
                f"全员身份公示：\n{player_list_str}"
            )
            game_room.status = "ended"
        else:
            # 猜错了
            await self._send_to_group(game_room,
                f"❌ {user_name} 猜词失败！正确答案是：{game_room.citizen_word}\n"
                f"游戏继续。"
            )
            # 继续下一轮
            game_room.round += 1
            game_room.speech_order = [p for p in game_room.players if p.is_alive]
            random.shuffle(game_room.speech_order)
            if len(game_room.speech_order) >= 5 and game_room.speech_order[0].role == "undercover":
                swap_idx = random.randrange(1, len(game_room.speech_order))
                game_room.speech_order[0], game_room.speech_order[swap_idx] = \
                    game_room.speech_order[swap_idx], game_room.speech_order[0]
            game_room.current_speaker_index = 0
            game_room.votes.clear()

            total_alive = len(game_room.speech_order)
            current_player = game_room.speech_order[0]
            yield MessageEventResult().at(current_player.user_name, current_player.user_id).message(
                f" 第 {game_room.round} 轮发言开始！请使用 /uc say <内容> 发言（发言次序 1/{total_alive}）"
            )

    def _check_winner(self, game_room: GameRoom) -> str | None:
        """检查游戏是否结束，返回获胜方或 None
        平民胜利条件：卧底和白板都出局
        卧底胜利条件：卧底存活数 >= 平民存活数
        """
        alive_players = [p for p in game_room.players if p.is_alive]
        alive_whiteboards = [p for p in alive_players if p.role == "whiteboard"]
        alive_good = [p for p in alive_players if p.role in ("citizen", "whiteboard")]
        alive_undercovers = [p for p in alive_players if p.role == "undercover"]

        # 卧底和白板都出局 → 平民胜利
        if len(alive_undercovers) == 0 and len(alive_whiteboards) == 0:
            return "平民"
        # 卧底数量 >= 平民（白板也算） → 卧底胜利
        elif len(alive_undercovers) >= len(alive_good):
            return "卧底"
        return None

    @uc.command("end")
    async def end_game(self, event: AstrMessageEvent):
        """结束游戏"""
        user_id = event.get_sender_id()

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if game_room.owner_id != user_id:
            yield event.plain_result("只有房主可以结束游戏")
            return

        # 清理所有玩家状态
        for player in game_room.players:
            if player.user_id in self.user_rooms:
                del self.user_rooms[player.user_id]

        del self.game_rooms[room_id]
        yield event.plain_result("游戏已结束，房间已解散")

    @uc.command("add")
    async def add_word_pair(self, event: AstrMessageEvent, word1: str = "", word2: str = ""):
        """添加词语对"""
        if not word1 or not word2:
            yield event.plain_result("请输入两个词语，格式：/uc add <词语1> <词语2>")
            return

        if [word1, word2] not in self.word_pairs and [word2, word1] not in self.word_pairs:
            self.word_pairs.append([word1, word2])
            self.save_word_pairs(self.word_pairs)
            yield event.plain_result(f"词语对添加成功：{word1} - {word2}")
        else:
            yield event.plain_result("该词语对已存在")

    @uc.command("list")
    async def list_games(self, event: AstrMessageEvent):
        """查看游戏列表"""
        if not self.game_rooms:
            yield event.plain_result("当前没有游戏房间")
            return

        game_list = "当前游戏房间列表：\n"
        for room_id, game_room in self.game_rooms.items():
            game_list += f"房间号：{room_id} | 状态：{game_room.status} | 玩家数：{len(game_room.players)}\n"

        yield event.plain_result(game_list)

    @uc.command("word")
    async def get_word(self, event: AstrMessageEvent):
        """获取自己的词语（建议私聊使用）"""
        user_id = event.get_sender_id()

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if game_room.status != "playing":
            yield event.plain_result("游戏未开始")
            return

        player = next((p for p in game_room.players if p.user_id == user_id), None)
        if not player:
            yield event.plain_result("未找到玩家信息")
            return

        if not player.is_alive:
            yield event.plain_result("你已被淘汰")
            return

        if player.role == "whiteboard":
            yield event.plain_result("你是【白板】，没有词语！请根据其他人的描述推测词语。\n如果被票出局，你将获得一次猜词机会。")
        else:
            yield event.plain_result(f"你的词语是：{player.word}\n(请确保你在私聊中查看此消息)")

    def load_word_pairs(self) -> list:
        """加载词语库，以 word_pairs.json 为准"""
        if os.path.exists(self.word_pairs_file):
            try:
                with open(self.word_pairs_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return self.get_default_word_pairs()
        else:
            defaults = self.get_default_word_pairs()
            self.save_word_pairs(defaults)
            return defaults

    def save_word_pairs(self, word_pairs: list):
        """保存词语库"""
        with open(self.word_pairs_file, 'w', encoding='utf-8') as f:
            json.dump(word_pairs, f, ensure_ascii=False, indent=2)

    def get_default_word_pairs(self) -> list:
        """获取默认词语库"""
        return [
            # 原有词库
            ["苹果", "梨"],
            ["电脑", "手机"],
            ["篮球", "足球"],
            ["牛奶", "豆浆"],
            ["面包", "蛋糕"],
            ["红色", "蓝色"],
            ["猫", "狗"],
            ["书", "杂志"],
            ["沙发", "椅子"],
            ["电视", "电影"],
            ["自行车", "电动车"],
            ["火车", "高铁"],
            ["飞机", "直升机"],
            ["老师", "学生"],
            ["医生", "护士"],
            # 动物类
            ["狮子", "老虎"],
            ["海豚", "鲸鱼"],
            ["斑马", "马"],
            ["兔子", "野兔"],
            ["青蛙", "蟾蜍"],
            ["老鹰", "鸽子"],
            ["乌鸦", "喜鹊"],
            ["飞蛾", "蝴蝶"],
            ["乌龟", "甲鱼"],
            ["蜥蜴", "壁虎"],
            ["猎豹", "豹子"],
            ["鸡", "鸭"],
            ["鲨鱼", "海豚"],
            ["蛇", "蜥蜴"],
            # 美食类
            ["火锅", "麻辣烫"],
            ["饺子", "包子"],
            ["汉堡", "三明治"],
            ["咖啡", "茶"],
            ["可乐", "雪碧"],
            ["白酒", "啤酒"],
            ["西兰花", "花菜"],
            ["肉夹馍", "驴肉火烧"],
            ["油条", "麻花"],
            ["口香糖", "木糖醇"],
            ["牛排", "羊排"],
            ["凉皮", "烤冷面"],
            ["麻婆豆腐", "皮蛋豆腐"],
            ["鱼香肉丝", "四喜丸子"],
            ["米饭", "面条"],
            ["薯片", "虾条"],
            ["雪糕", "冰淇淋"],
            ["豆浆", "米糊"],
            ["酱油", "醋"],
            # 品牌类
            ["耐克", "阿迪达斯"],
            ["麦当劳", "肯德基"],
            ["星巴克", "瑞幸"],
            ["可口可乐", "百事可乐"],
            ["苹果", "华为"],
            ["微信", "QQ"],
            ["支付宝", "微信支付"],
            ["滴滴", "高德"],
            # 影视娱乐类
            ["周杰伦", "林俊杰"],
            ["五月天", "苏打绿"],
            ["漫威", "DC"],
            ["哈利波特", "指环王"],
            ["甄嬛传", "芈月传"],
            ["盗梦空间", "星际穿越"],
            ["复仇者联盟", "正义联盟"],
            ["刘德华", "梁朝伟"],
            ["神雕侠侣", "天龙八部"],
            ["天天向上", "非诚勿扰"],
            ["福尔摩斯", "工藤新一"],
            ["郭德纲", "周立波"],
            ["十面埋伏", "四面楚歌"],
            ["成吉思汗", "努尔哈赤"],
            ["梁山伯与祝英台", "罗密欧与朱丽叶"],
            ["贵妃醉酒", "黛玉葬花"],
            # 日常物品类
            ["吉他", "钢琴"],
            ["近视眼镜", "隐形眼镜"],
            ["袜子", "丝袜"],
            ["香水", "花露水"],
            ["蜡烛", "香薰"],
            ["枕头", "抱枕"],
            ["毯子", "被子"],
            ["拖把", "扫把"],
            ["碗", "碟子"],
            ["空调", "风扇"],
            ["冰箱", "冰柜"],
            ["洗衣机", "烘干机"],
            ["微波炉", "烤箱"],
            ["电梯", "扶梯"],
            # 自然/地理类
            ["太阳", "月亮"],
            ["意大利", "法国"],
            ["夏天", "冬天"],
            ["春天", "秋天"],
            ["寺庙", "道观"],
            ["玫瑰", "月季"],
            ["牡丹", "芍药"],
            ["长江", "黄河"],
            ["泰山", "黄山"],
            ["海滩", "沙滩"],
            ["江", "河"],
            ["湖", "水库"],
            # 人物职业类
            ["警察", "消防员"],
            ["厨师", "糕点师"],
            ["演员", "歌手"],
            ["律师", "法官"],
            ["飞行员", "宇航员"],
            # 游戏类
            ["原神", "塞尔达传说"],
            ["崩坏3", "战双帕弥什"],
            ["明日方舟", "少女前线"],
            ["英雄联盟", "王者荣耀"],
            ["我的世界", "迷你世界"],
            ["和平精英", "使命召唤手游"],
            ["阴阳师", "百闻牌"],
            ["FGO", "碧蓝航线"],
            ["魔兽世界", "最终幻想14"],
            ["CSGO", "无畏契约"],
            ["星际争霸", "魔兽争霸"],
            ["巫师3", "上古卷轴5"],
            ["鬼泣", "猎天使魔女"],
            ["黑暗之魂", "艾尔登法环"],
            ["只狼", "对马岛之魂"],
            ["怪物猎人", "讨鬼传"],
            ["超级马里奥", "索尼克"],
            ["精灵宝可梦", "数码宝贝"],
            ["刺客信条", "看门狗"],
            ["GTA5", "热血无赖"],
            ["植物大战僵尸", "保卫萝卜"],
            ["愤怒的小鸟", "割绳子"],
            ["炉石传说", "影之诗"],
            ["绝地求生", "APEX英雄"],
            ["剑网3", "天涯明月刀"],
            ["恋与制作人", "光与夜之恋"],
            ["赛马娘", "偶像大师"],
            ["DOTA2", "风暴英雄"],
            ["坦克世界", "战争雷霆"],
            ["文明6", "全面战争"],
            ["星露谷物语", "牧场物语"],
            ["空洞骑士", "奥日与黑暗森林"],
            ["泰拉瑞亚", "星界边境"],
            ["生化危机", "寂静岭"],
            # 二次元/动漫类
            ["火影忍者", "海贼王"],
            ["进击的巨人", "东京喰种"],
            ["鬼灭之刃", "咒术回战"],
            ["钢之炼金术师", "魔法禁书目录"],
            ["柯南", "金田一"],
            ["龙珠", "幽游白书"],
            ["新世纪福音战士", "机动战士高达"],
            ["千与千寻", "你的名字"],
            ["初音未来", "洛天依"],
            ["B站", "A站"],
            ["手办", "模型"],
            ["漫展", "同人展"],
            ["刀剑神域", "记录的地平线"],
            ["Re:Zero", "命运石之门"],
            ["物语系列", "凉宫春日的忧郁"],
            ["银魂", "日常"],
            ["一拳超人", "灵能百分百"],
            ["某科学的超电磁炮", "魔法少女小圆"],
            ["Fate/Zero", "空之境界"],
            ["紫罗兰永恒花园", "冰菓"],
            ["CLANNAD", "未闻花名"],
            ["轻音少女", "孤独摇滚"],
            ["葬送的芙莉莲", "迷宫饭"],
            # 二次元角色类 — 同作品
            ["鸣人", "佐助"],
            ["路飞", "艾斯"],
            ["炭治郎", "善逸"],
            ["五条悟", "虎杖悠仁"],
            ["艾伦", "莱纳"],
            ["坂田银时", "土方十四郎"],
            ["鲁路修", "朱雀"],
            ["绫波丽", "明日香"],
            ["小圆", "晓美焰"],
            ["阿库娅", "惠惠"],
            ["折木奉太郎", "千反田爱瑠"],
            ["桐谷和人", "亚丝娜"],
            ["冈部伦太郎", "牧濑红莉栖"],
            ["立花泷", "宫水三叶"],
            ["千寻", "白龙"],
            ["杀生丸", "犬夜叉"],
            ["渚薰", "碇真嗣"],
            ["平和岛静雄", "折原临也"],
            ["太宰治", "中原中也"],
            ["金木研", "雾岛董香"],
            ["菜月昴", "雷姆"],
            ["和真", "达克妮丝"],
            ["高木", "西片"],
            ["辉夜", "白银御行"],
            ["薇尔莉特", "基尔伯特"],
            ["逢坂大河", "栉枝实乃梨"],
            ["阿良良木历", "战场原黑仪"],
            ["比企谷八幡", "雪之下雪乃"],
            ["卫宫士郎", "远坂凛"],
            ["阿虚", "凉宫春日"],
            ["苗木诚", "雾切响子"],
            ["爱德华", "阿尔冯斯"],
            # 二次元角色类 — 跨作品相似角色
            ["工藤新一", "怪盗基德"],
            ["Saber", "尼禄"],
            ["Saber", "贞德"],
            ["鸣人", "路飞"],
            ["吉尔伽美什", "蓝染惣右介"],
            ["香克斯", "基尔达斯"],
            ["楪祈", "我妻由乃"],
            ["琦玉", "齐木楠雄"],
            ["时崎狂三", "五河琴里"],
            ["御坂美琴", "一方通行"],
            ["和泉纱雾", "雪之下雪乃"],
            ["爱蜜莉雅", "雷姆"],
            ["惠惠", "悠悠"],
            ["康娜", "宫内莲华"],
            ["樱岛麻衣", "古贺朋绘"],
            ["夜斗", "毗沙门天"],
            ["酒吞童子", "茨木童子"],
            ["两仪式", "黑桐干也"],
        ]

    async def terminate(self):
        """插件销毁时调用"""
        logger.info("谁是卧底插件已卸载")
