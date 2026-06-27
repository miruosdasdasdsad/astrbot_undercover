from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
import random
import json
import os
import re

# 特殊模式触发概率
SPECIAL_MODE_PROBABILITY = 0.05


class Player:
    """玩家类"""
    def __init__(self, user_id, user_name):
        self.user_id = user_id
        self.user_name = user_name
        self.is_alive = True
        self.role = None  # citizen, undercover, whiteboard
        self.word = None
        self.last_speech = ""


class GameRoom:
    """游戏房间类"""
    def __init__(self, room_id, owner_id, owner_name):
        self.room_id = room_id
        self.owner_id = owner_id
        self.owner_name = owner_name
        self.players = []  # Player 对象列表
        self.status = "waiting"  # waiting, playing, ended
        self.speech_order = []
        self.current_speaker_index = 0
        self.votes = {}  # user_id: voted_user_id
        self.round = 1
        self.group_session_str = ""
        self.whiteboard_guessing = False
        self.whiteboard_player = None
        self.citizen_word = ""
        # 游戏设置（功能1）
        self.enable_whiteboard = True   # 是否存在白板
        self.selected_category = "全部"  # 选择的词库类别
        self.private_vote = True        # 是否允许私聊投票（群聊始终可投票）
        # 特殊模式（功能4）
        self.special_mode = False       # 1卧底+全白板模式
        self.final_guess_phase = False  # 卧底被票后的最终猜词阶段
        self.whiteboard_guessed = {}    # user_id: bool 白板是否已猜过词


@register("undercover", "BB0813", "谁是卧底游戏插件", "1.4.0")
class UndercoverPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.game_rooms = {}
        self.user_rooms = {}
        self.word_pairs_file = "word_pairs.json"
        self.word_pairs = self.load_word_pairs()
        self.room_counter = 1

    async def initialize(self):
        """插件初始化"""
        logger.info("谁是卧底插件 v1.4.0 初始化成功")

    # ── 词库管理 ─────────────────────────────────────────────

    def load_word_pairs(self) -> dict:
        """加载词语库，自动迁移 v1→v2 格式"""
        if os.path.exists(self.word_pairs_file):
            try:
                with open(self.word_pairs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("version") == 2:
                    return data
                elif isinstance(data, list):
                    logger.info("检测到 v1 格式词库，正在自动迁移到 v2...")
                    migrated = {"version": 2, "categories": {"综合": data}}
                    self.save_word_pairs(migrated)
                    return migrated
            except Exception as e:
                logger.warning(f"加载词库失败：{e}，使用默认词库")
        defaults = self.get_default_word_pairs()
        self.save_word_pairs(defaults)
        return defaults

    def save_word_pairs(self, word_pairs: dict):
        """保存词语库"""
        with open(self.word_pairs_file, 'w', encoding='utf-8') as f:
            json.dump(word_pairs, f, ensure_ascii=False, indent=2)

    def get_word_groups_for_game(self, category: str = "全部") -> list:
        """获取指定类别的词组列表。category="全部" 时返回所有类别的词组"""
        categories = self.word_pairs.get("categories", {})
        if not categories:
            return []
        if category == "全部":
            result = []
            for cat_words in categories.values():
                result.extend(cat_words)
            return result
        return list(categories.get(category, []))

    def pick_words_from_group(self, word_group: list) -> tuple:
        """从词组（2-N个词）中随机选 2 个，返回 (citizen_word, undercover_word)"""
        a, b = random.sample(word_group, 2)
        if random.random() < 0.5:
            return a, b
        else:
            return b, a

    def get_available_categories(self) -> list:
        """获取所有可用类别名"""
        return list(self.word_pairs.get("categories", {}).keys())

    def get_default_word_pairs(self) -> dict:
        """获取默认词语库（v2 格式）"""
        return {
            "version": 2,
            "categories": {
                "游戏": [
                    ["原神", "塞尔达传说"],
                    ["明日方舟", "少女前线"],
                    ["英雄联盟", "王者荣耀"],
                    ["和平精英", "使命召唤手游"],
                    ["FGO", "碧蓝航线"],
                    ["魔兽世界", "最终幻想14"],
                    ["CSGO", "无畏契约"],
                    ["星际争霸", "帝国时代"],
                    ["巫师3", "上古卷轴5"],
                    ["鬼泣", "猎天使魔女"],
                    ["黑暗之魂", "艾尔登法环"],
                    ["只狼", "对马岛之魂"],
                    ["超级马里奥", "索尼克"],
                    ["刺客信条", "看门狗"],
                    ["GTA5", "热血无赖"],
                    ["植物大战僵尸", "保卫萝卜"],
                    ["愤怒的小鸟", "割绳子"],
                    ["绝地求生", "APEX英雄"],
                    ["剑网3", "天涯明月刀"],
                    ["赛马娘", "偶像大师"],
                    ["DOTA2", "风暴英雄"],
                    ["空洞骑士", "奥日与黑暗森林"],
                    ["生化危机", "寂静岭"],
                    ["我的世界", "迷你世界", "泰拉瑞亚"],
                    ["崩坏3", "战双帕弥什", "鸣潮"],
                    ["炉石传说", "影之诗", "游戏王"],
                ],
                "动漫": [
                    ["火影忍者", "海贼王", "死神"],
                    ["鬼灭之刃", "咒术回战"],
                    ["初音未来", "洛天依"],
                    ["某科学的超电磁炮", "魔法少女小圆"],
                    ["轻音少女", "孤独摇滚"],
                    ["葬送的芙莉莲", "迷宫饭"],
                    ["精灵宝可梦", "数码宝贝"],
                    ["进击的巨人", "东京喰种"],
                    ["龙珠", "幽游白书"],
                    ["新世纪福音战士", "机动战士高达"],
                    ["千与千寻", "你的名字"],
                    ["刀剑神域", "记录的地平线"],
                    ["Re:Zero", "命运石之门"],
                    ["银魂", "日常"],
                    ["一拳超人", "灵能百分百"],
                    ["紫罗兰永恒花园", "冰菓"],
                    ["CLANNAD", "未闻花名"],
                    ["五条悟", "宿傩"],
                    ["时崎狂三", "五河琴里"],
                    ["御坂美琴", "一方通行"],
                    ["鸣人", "佐助"],
                    ["路飞", "艾斯"],
                    ["炭治郎", "善逸"],
                    ["艾伦", "莱纳"],
                    ["坂田银时", "土方十四郎"],
                    ["鲁路修", "朱雀"],
                    ["绫波丽", "明日香"],
                    ["小圆", "晓美焰"],
                    ["阿库娅", "惠惠"],
                    ["桐谷和人", "亚丝娜"],
                    ["冈部伦太郎", "牧濑红莉栖"],
                    ["立花泷", "宫水三叶"],
                    ["千寻", "白龙"],
                    ["杀生丸", "犬夜叉"],
                    ["渚薰", "碇真嗣"],
                    ["太宰治", "中原中也"],
                    ["金木研", "雾岛董香"],
                    ["菜月昴", "雷姆"],
                    ["辉夜", "白银御行"],
                    ["薇尔莉特", "基尔伯特"],
                    ["逢坂大河", "栉枝实乃梨"],
                    ["阿良良木历", "战场原黑仪"],
                    ["比企谷八幡", "雪之下雪乃"],
                    ["卫宫士郎", "远坂凛"],
                    ["阿虚", "凉宫春日"],
                    ["爱德华", "阿尔冯斯"],
                    ["Saber", "尼禄", "贞德"],
                    ["琦玉", "齐木楠雄"],
                ],
                "影视": [
                    ["漫威", "DC"],
                    ["哈利波特", "指环王"],
                    ["盗梦空间", "星际穿越"],
                    ["复仇者联盟", "正义联盟"],
                    ["甄嬛传", "芈月传"],
                    ["神雕侠侣", "天龙八部"],
                    ["十面埋伏", "四面楚歌"],
                    ["梁山伯与祝英台", "罗密欧与朱丽叶"],
                    ["周杰伦", "林俊杰"],
                    ["五月天", "苏打绿"],
                    ["刘德华", "梁朝伟"],
                    ["郭德纲", "周立波"],
                ],
                "美食": [
                    ["火锅", "麻辣烫"],
                    ["饺子", "包子"],
                    ["汉堡", "三明治"],
                    ["咖啡", "茶"],
                    ["可乐", "雪碧"],
                    ["白酒", "啤酒"],
                    ["西兰花", "花菜"],
                    ["肉夹馍", "驴肉火烧"],
                    ["油条", "麻花"],
                    ["牛排", "羊排"],
                    ["凉皮", "烤冷面"],
                    ["麻婆豆腐", "皮蛋豆腐"],
                    ["鱼香肉丝", "四喜丸子"],
                    ["米饭", "面条"],
                    ["薯片", "虾条"],
                    ["雪糕", "冰淇淋"],
                    ["豆浆", "米糊"],
                    ["酱油", "醋"],
                ],
                "日常": [
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
                    ["吉他", "钢琴"],
                    ["近视眼镜", "隐形眼镜"],
                    ["袜子", "丝袜"],
                    ["香水", "花露水"],
                    ["枕头", "抱枕"],
                    ["毯子", "被子"],
                    ["拖把", "扫把"],
                    ["碗", "碟子"],
                    ["空调", "风扇"],
                    ["冰箱", "冰柜"],
                    ["洗衣机", "烘干机"],
                    ["微波炉", "烤箱"],
                    ["电梯", "扶梯"],
                    ["太阳", "月亮"],
                    ["意大利", "法国"],
                    ["夏天", "冬天"],
                    ["春天", "秋天"],
                    ["寺庙", "道观"],
                    ["玫瑰", "月季"],
                    ["牡丹", "芍药"],
                    ["长江", "黄河"],
                    ["泰山", "黄山"],
                    ["江", "河"],
                    ["湖", "水库"],
                    ["警察", "消防员"],
                    ["厨师", "糕点师"],
                    ["演员", "歌手"],
                    ["律师", "法官"],
                    ["飞行员", "宇航员"],
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
                    ["蛇", "蜥蜴"],
                    ["耐克", "阿迪达斯"],
                    ["麦当劳", "肯德基"],
                    ["星巴克", "瑞幸"],
                    ["可口可乐", "百事可乐"],
                    ["苹果", "华为"],
                    ["微信", "QQ"],
                    ["支付宝", "微信支付"],
                    ["滴滴", "高德"],
                    ["福尔摩斯", "工藤新一"],
                    ["成吉思汗", "努尔哈赤"],
                    ["贵妃醉酒", "黛玉葬花"],
                    ["口香糖", "木糖醇"],
                ],
            },
        }

    # ── 指令入口 ─────────────────────────────────────────────

    @filter.command_group("uc")
    def uc(self):
        pass

    @uc.command("help")
    async def uc_help(self, event: AstrMessageEvent):
        help_text = (
            "🎮 谁是卧底游戏指令：\n"
            "/uc help - 查看帮助\n"
            "/uc create - 创建游戏房间\n"
            "/uc join <房间号> - 加入游戏房间\n"
            "/uc config [设置] [值] - 查看/修改游戏设置（房主，游戏开始前）\n"
            "/uc categories - 查看可用词库类别\n"
            "/uc start - 开始游戏（房主）\n"
            "/uc leave - 离开当前房间\n"
            "/uc say <内容> - 游戏中发言\n"
            "/uc vote <玩家> - 游戏中投票\n"
            "/uc guess <词语> - 白板猜词\n"
            "/uc end - 结束游戏（房主）\n"
            "/uc add <词语1> <词语2> [词语3] ... - 添加词语到词库\n"
            "/uc word - 查看我的词语（请私聊使用）\n"
            "/uc list - 查看游戏列表\n"
        )
        yield event.plain_result(help_text)

    # ── 房间管理 ─────────────────────────────────────────────

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

        yield event.plain_result(
            f"🎮 游戏房间创建成功！房间号：{room_id}\n"
            f"房主：{user_name}\n"
            f"使用 /uc join {room_id} 邀请其他玩家加入\n\n"
            f"💡 房主可使用 /uc config 调整游戏设置后再开始"
        )

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

    # ── 游戏设置（功能1）─────────────────────────────────────

    @uc.command("config")
    async def config_game(self, event: AstrMessageEvent, setting: str = "", value: str = ""):
        """查看或修改游戏设置"""
        user_id = event.get_sender_id()

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if game_room.owner_id != user_id:
            yield event.plain_result("只有房主可以修改游戏设置")
            return

        if game_room.status != "waiting":
            yield event.plain_result("游戏已开始，无法修改设置")
            return

        # 无参数 → 查看当前设置
        if not setting:
            cats = self.get_available_categories()
            cat_display = game_room.selected_category if game_room.selected_category in cats else "全部"
            yield event.plain_result(
                f"⚙️ 房间 {room_id} 游戏设置：\n"
                f"  白板：{'开启 ✅' if game_room.enable_whiteboard else '关闭 ❌'}\n"
                f"  词库：{cat_display}（共{len(cats)}个类别可选）\n"
                f"  私聊投票：{'开启 ✅' if game_room.private_vote else '关闭 ❌（仅群聊可投票）'}\n\n"
                f"修改设置：/uc config <设置项> <值>\n"
                f"  示例：/uc config whiteboard off\n"
                f"  示例：/uc config category 游戏\n"
                f"  示例：/uc config vote public"
            )
            return

        setting = setting.lower()
        value = value.lower()

        if setting == "whiteboard":
            if value in ("on", "true", "开", "开启"):
                game_room.enable_whiteboard = True
                yield event.plain_result("✅ 白板已开启")
            elif value in ("off", "false", "关", "关闭"):
                game_room.enable_whiteboard = False
                yield event.plain_result("✅ 白板已关闭")
            else:
                yield event.plain_result("无效值，请使用 on/off")

        elif setting == "category" or setting == "类别" or setting == "词库":
            cats = self.get_available_categories()
            if not value or value in ("全部", "all"):
                game_room.selected_category = "全部"
                yield event.plain_result("✅ 词库已设置为：全部")
            elif value in cats:
                game_room.selected_category = value
                yield event.plain_result(f"✅ 词库已设置为：{value}")
            else:
                yield event.plain_result(f"无效类别，可用类别：全部、{', '.join(cats)}")

        elif setting == "vote" or setting == "投票":
            if value in ("private", "私聊", "开", "开启", "on", "true"):
                game_room.private_vote = True
                yield event.plain_result("✅ 私聊投票已开启（群聊+私聊均可投票）")
            elif value in ("public", "群聊", "关", "关闭", "off", "false"):
                game_room.private_vote = False
                yield event.plain_result("✅ 私聊投票已关闭（仅群聊可投票）")
            else:
                yield event.plain_result("无效值，请使用 private/public")

        else:
            yield event.plain_result(f"未知设置项：{setting}，可用设置：whiteboard / category / vote")

    @uc.command("categories")
    async def list_categories(self, event: AstrMessageEvent):
        """查看可用词库类别"""
        cats = self.get_available_categories()
        if not cats:
            yield event.plain_result("当前没有可用词库类别")
            return

        lines = ["📚 可用词库类别：", ""]
        for cat in cats:
            count = len(self.word_pairs["categories"].get(cat, []))
            lines.append(f"  • {cat}（{count}组词）")
        lines.append("")
        lines.append("使用 /uc config category <类别名> 选择词库，或 /uc config category all 使用全部")
        yield event.plain_result("\n".join(lines))

    # ── 游戏流程 ─────────────────────────────────────────────

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

        # 根据设置筛选词库
        word_groups = self.get_word_groups_for_game(game_room.selected_category)
        if not word_groups:
            yield event.plain_result("选择的词库中没有词语，请更换词库或使用 /uc config category all")
            return

        game_room.status = "playing"

        # 从词组中随机选一组，再从中随机选2个词
        word_group = random.choice(word_groups)
        citizen_word, undercover_word = self.pick_words_from_group(word_group)
        game_room.citizen_word = citizen_word

        num_players = len(game_room.players)

        # ── 功能4：特殊模式检测 ──
        # 白板开启 + 概率触发 + 至少4人
        if game_room.enable_whiteboard and num_players >= 4 and random.random() < SPECIAL_MODE_PROBABILITY:
            game_room.special_mode = True
            game_room.whiteboard_guessed = {}

            random.shuffle(game_room.players)
            # 1人为卧底（有词），其余全为白板（无词）
            undercover_player = game_room.players[0]
            undercover_player.role = "undercover"
            undercover_player.word = undercover_word

            for p in game_room.players[1:]:
                p.role = "whiteboard"
                p.word = ""
                game_room.whiteboard_guessed[p.user_id] = False

            # 建立发言顺序
            game_room.speech_order = [p for p in game_room.players if p.is_alive]
            random.shuffle(game_room.speech_order)
            game_room.current_speaker_index = 0
            game_room.votes.clear()
            game_room.round = 1
            game_room.group_session_str = event.unified_msg_origin
            game_room.final_guess_phase = False

            # 私聊通知
            platform_id = event.get_platform_id()
            failed_players = []
            for player in game_room.players:
                try:
                    private_session = MessageSession(
                        platform_name=platform_id,
                        message_type=MessageType.FRIEND_MESSAGE,
                        session_id=player.user_id,
                    )
                    if player.role == "undercover":
                        await self.context.send_message(
                            private_session,
                            MessageEventResult().message(
                                f"🎮 谁是卧底 游戏开始！\n"
                                f"📝 你的词语是：{player.word}\n\n"
                                f"💡 请勿泄露你的词语！在发言环节描述它，让其他人猜不到你。"
                            ),
                        )
                    else:
                        await self.context.send_message(
                            private_session,
                            MessageEventResult().message(
                                f"🎮 谁是卧底 游戏开始！\n"
                                f"📝 你是【白板】，没有词语！\n"
                                f"💡 请根据其他人的描述推测词语，在发言环节即兴发挥。\n"
                                f"💡 你可以随时使用 /uc guess <词语> 猜词，猜对即可获胜！"
                            ),
                        )
                except Exception:
                    failed_players.append(player.user_name)

            if failed_players:
                failed_list = "、".join(failed_players)
                tip = f"\n⚠️ 以下玩家可能未收到私聊，请手动发送 /uc word 查看词语：{failed_list}"
            else:
                tip = ""

            total_alive = len(game_room.speech_order)
            yield event.plain_result(
                f"🎮 游戏开始！\n"
                f"👥 发言顺序：{' → '.join(p.user_name for p in game_room.speech_order)}\n"
                f"📨 词语和身份已私聊发送给各位玩家{tip}"
            )

            current_player = game_room.speech_order[0]
            yield MessageEventResult().at(current_player.user_name, current_player.user_id).message(
                f" 第 {game_room.round} 轮发言开始！请使用 /uc say <内容> 发言（发言次序 1/{total_alive}）"
            )
            return

        # ── 普通模式 ──

        # 卧底数量
        if num_players <= 8:
            num_undercover = 1
        else:
            num_undercover = 2

        random.shuffle(game_room.players)

        for i, player in enumerate(game_room.players):
            if i < num_undercover:
                player.role = "undercover"
                player.word = undercover_word
            else:
                player.role = "citizen"
                player.word = citizen_word

        # 白板：从平民中随机抽一个（5人及以上 + 设置开启）
        if game_room.enable_whiteboard and num_players >= 5:
            whiteboard_candidates = [p for p in game_room.players if p.role == "citizen"]
            if whiteboard_candidates:
                wb = random.choice(whiteboard_candidates)
                wb.role = "whiteboard"
                wb.word = ""

        # 建立发言顺序
        game_room.speech_order = [p for p in game_room.players if p.is_alive]
        random.shuffle(game_room.speech_order)
        if len(game_room.speech_order) >= 5 and game_room.speech_order[0].role == "undercover":
            swap_idx = random.randrange(1, len(game_room.speech_order))
            game_room.speech_order[0], game_room.speech_order[swap_idx] = \
                game_room.speech_order[swap_idx], game_room.speech_order[0]
        game_room.current_speaker_index = 0
        game_room.votes.clear()
        game_room.round = 1
        game_room.group_session_str = event.unified_msg_origin

        total_alive = len(game_room.speech_order)

        # 私聊通知
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

    @uc.command("say")
    async def say(self, event: AstrMessageEvent):
        """游戏中发言"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
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

        game_room.speech_order = [p for p in game_room.speech_order if p.is_alive]
        total_alive = len(game_room.speech_order)

        if game_room.current_speaker_index >= total_alive:
            yield event.plain_result("当前发言环节已结束，请使用 /uc vote <玩家> 进行投票")
            return

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

        player.last_speech = text
        game_room.current_speaker_index += 1
        spoken_count = game_room.current_speaker_index

        yield event.plain_result(f"💬 {user_name}：{text}\n✅ 发言已记录，当前发言次序({spoken_count}/{total_alive})")

        if game_room.current_speaker_index >= total_alive:
            game_room.votes.clear()
            speech_summary = "\n".join(
                f"  {p.user_name}：{p.last_speech}" for p in game_room.speech_order
            )
            yield event.plain_result(
                f"🎯 第 {game_room.round} 轮发言结束！\n"
                f"📋 本轮描述：\n{speech_summary}\n"
                f"🗳️ 请使用 /uc vote <玩家> 投票（{'私聊或群聊均可' if game_room.private_vote else '仅限群聊投票'}）"
            )
        else:
            next_player = game_room.speech_order[game_room.current_speaker_index]
            next_index = game_room.current_speaker_index + 1
            yield MessageEventResult().at(next_player.user_name, next_player.user_id).message(
                f" 请使用 /uc say <内容> 发言（发言次序 {next_index}/{total_alive}）"
            )

    @uc.command("vote")
    async def vote(self, event: AstrMessageEvent, target_name: str = ""):
        """游戏中投票"""
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

        game_room.speech_order = [p for p in game_room.speech_order if p.is_alive]

        if game_room.current_speaker_index < len(game_room.speech_order):
            yield event.plain_result("当前仍在发言环节，无法投票")
            return

        # 功能1：私聊投票权限检查（群聊始终允许）
        is_group_msg = (event.unified_msg_origin == game_room.group_session_str)
        if not is_group_msg and not game_room.private_vote:
            yield event.plain_result("当前游戏设置为禁止私聊投票，请在群聊中投票")
            return

        if user_id in game_room.votes:
            yield event.plain_result("你已经投过票了")
            return

        voter = next((p for p in game_room.players if p.user_id == user_id), None)
        if not voter or not voter.is_alive:
            yield event.plain_result("你已被淘汰，无法投票")
            return

        if target_name.strip() == "弃权":
            game_room.votes[user_id] = None
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

        progress_msg = f"🗳️ 已投票 {voted_count}/{total_count}"
        await self._send_to_group(game_room, progress_msg)

        yield event.plain_result("✅ 你的投票已记录")

        if voted_count >= total_count:
            async for result in self._process_vote_result(event, game_room):
                yield result

    async def _process_vote_result(self, event: AstrMessageEvent, game_room: GameRoom):
        """处理投票结果"""
        # 统计票数
        vote_counts = {}
        for voted_id in game_room.votes.values():
            if voted_id is not None:
                vote_counts[voted_id] = vote_counts.get(voted_id, 0) + 1

        if not vote_counts:
            # 全部弃权
            await self._send_to_group(game_room, "⚖️ 本轮全部弃权，无人被票出局！")
            yield_result = self._do_next_round(game_room)
            if yield_result:
                yield yield_result
            return

        max_votes = max(vote_counts.values())
        alive_players = [p for p in game_room.players if p.is_alive]
        eliminated_players = [p for p in alive_players if vote_counts.get(p.user_id, 0) == max_votes]

        if len(eliminated_players) > 1:
            # 平票
            await self._send_to_group(game_room,
                f"⚖️ 投票结果平票：{', '.join(p.user_name for p in eliminated_players)}\n请重新投票！"
            )
            game_room.votes.clear()
            return

        eliminated = eliminated_players[0]

        # ── 功能4：特殊模式 ──
        if game_room.special_mode:
            if eliminated.role == "whiteboard":
                eliminated.is_alive = False
                result_msg = f"🗳️ 投票结果：\n玩家 {eliminated.user_name} 被票出局！"
                await self._send_to_group(game_room, result_msg)

                # 检查游戏是否结束
                winner = self._check_winner(game_room)
                if winner:
                    player_list_str = self._format_player_list(game_room)
                    await self._send_to_group(game_room, f"🏆 游戏结束！{winner}胜利！\n\n全员身份公示：\n{player_list_str}")
                    game_room.status = "ended"
                    return

                yield_result = self._do_next_round(game_room)
                if yield_result:
                    yield yield_result
                return

            elif eliminated.role == "undercover":
                # 卧底被票出 → 触发最终猜词阶段
                eliminated.is_alive = False
                game_room.final_guess_phase = True
                # 重置所有存活白板的猜词机会
                for p in game_room.players:
                    if p.is_alive and p.role == "whiteboard":
                        game_room.whiteboard_guessed[p.user_id] = False
                await self._send_to_group(game_room,
                    f"🗳️ 投票结果：\n"
                    f"玩家 {eliminated.user_name} 被票出局！\n"
                    f"💡 所有存活玩家获得一次猜词机会！请私聊使用 /uc guess <词语> 猜词！"
                )

                # 私聊通知所有存活白板
                platform_id = event.get_platform_id()
                for p in game_room.players:
                    if p.is_alive and p.role == "whiteboard":
                        try:
                            private_session = MessageSession(
                                platform_name=platform_id,
                                message_type=MessageType.FRIEND_MESSAGE,
                                session_id=p.user_id,
                            )
                            await self.context.send_message(
                                private_session,
                                MessageEventResult().message(
                                    f"🎯 最终猜词机会！\n请使用 /uc guess <词语> 猜词！"
                                ),
                            )
                        except Exception:
                            pass
                return

        # ── 普通模式 ──

        # 白板被票 → 猜词阶段
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

        winner = self._check_winner(game_room)
        if winner:
            player_list_str = self._format_player_list(game_room)
            await self._send_to_group(game_room, f"🏆 游戏结束！{winner}胜利！\n\n全员身份公示：\n{player_list_str}")
            game_room.status = "ended"
            return

        await self._send_to_group(game_room,
            f"🔄 第 {game_room.round + 1} 轮开始！\n"
            f"📋 存活玩家({len([p for p in game_room.players if p.is_alive])}人)："
            f"{', '.join(p.user_name for p in game_room.players if p.is_alive)}"
        )

        yield_result = self._do_next_round(game_room)
        if yield_result:
            yield yield_result

    def _do_next_round(self, game_room: GameRoom):
        """准备新一轮发言，返回要 yield 的 message 或 None"""
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
        if total_alive > 0:
            current_player = game_room.speech_order[0]
            return MessageEventResult().at(current_player.user_name, current_player.user_id).message(
                f" 第 {game_room.round} 轮发言开始！请使用 /uc say <内容> 发言（发言次序 1/{total_alive}）"
            )
        return None

    def _format_player_list(self, game_room: GameRoom) -> str:
        """格式化玩家身份列表"""
        return "\n".join([
            f"{p.user_name}：{'卧底' if p.role == 'undercover' else '白板' if p.role == 'whiteboard' else '平民'} - {p.word or '(无)'}"
            for p in game_room.players
        ])

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

    # ── 猜词（功能4 扩展）───────────────────────────────────

    @uc.command("guess")
    async def guess_word(self, event: AstrMessageEvent):
        """白板猜词（普通模式：被票后猜；特殊模式：随时可猜）"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        raw_msg = event.get_message_str()
        m = re.match(r'\S+\s+guess\s+(.+)', raw_msg, re.IGNORECASE)
        guess = m.group(1).strip() if m else ""

        if user_id not in self.user_rooms:
            yield event.plain_result("你不在任何游戏房间中")
            return

        room_id = self.user_rooms[user_id]
        game_room = self.game_rooms[room_id]

        if not guess:
            yield event.plain_result("请使用 /uc guess <词语> 猜词")
            return

        # ── 特殊模式猜词 ──
        if game_room.special_mode:
            player = next((p for p in game_room.players if p.user_id == user_id), None)
            if not player:
                yield event.plain_result("未找到玩家信息")
                return

            if player.role != "whiteboard":
                yield event.plain_result("你不是白板，无需猜词")
                return

            # 最终猜词阶段：任何人（存活白板）可猜，无视之前的猜测记录
            if game_room.final_guess_phase:
                if not player.is_alive:
                    yield event.plain_result("你已被淘汰")
                    return

                if guess == game_room.citizen_word:
                    player_list_str = self._format_player_list(game_room)
                    await self._send_to_group(game_room,
                        f"🎉 {user_name} 猜词正确！词语是：{game_room.citizen_word}\n"
                        f"🏆 【白板】{user_name} 获胜！\n\n全员身份公示：\n{player_list_str}"
                    )
                    game_room.status = "ended"
                else:
                    yield event.plain_result("❌ 猜词错误！")
                    game_room.whiteboard_guessed[user_id] = True
                    # 检查是否所有存活白板都已猜错
                    remaining = [p for p in game_room.players if p.is_alive and p.role == "whiteboard"
                                 and not game_room.whiteboard_guessed.get(p.user_id, False)]
                    if not remaining:
                        player_list_str = self._format_player_list(game_room)
                        await self._send_to_group(game_room,
                            f"所有存活玩家猜词均失败！正确答案是：{game_room.citizen_word}\n"
                            f"🏆 【卧底】获胜！\n\n全员身份公示：\n{player_list_str}"
                        )
                        game_room.status = "ended"
                return

            # 正常猜词（游戏进行中，每人一次机会）
            if not player.is_alive:
                yield event.plain_result("你已被淘汰，无法猜词")
                return

            if game_room.whiteboard_guessed.get(user_id, False):
                yield event.plain_result("你已经猜过词了，请等待最终猜词机会")
                return

            game_room.whiteboard_guessed[user_id] = True

            if guess == game_room.citizen_word:
                player_list_str = self._format_player_list(game_room)
                await self._send_to_group(game_room,
                    f"🎉 {user_name} 猜词正确！词语是：{game_room.citizen_word}\n"
                    f"🏆 【白板】{user_name} 获胜！\n\n全员身份公示：\n{player_list_str}"
                )
                game_room.status = "ended"
            else:
                yield event.plain_result("❌ 猜词错误！你已经用掉了猜词机会。")
            return

        # ── 普通模式猜词（被票白板） ──
        if not game_room.whiteboard_guessing:
            yield event.plain_result("当前没有猜词机会")
            return

        if game_room.whiteboard_player.user_id != user_id:
            yield event.plain_result("只有被票出的白板可以猜词")
            return

        game_room.whiteboard_guessing = False
        game_room.whiteboard_player = None

        if guess == game_room.citizen_word:
            player_list_str = self._format_player_list(game_room)
            await self._send_to_group(game_room,
                f"🎉 {user_name} 猜词正确！词语是：{game_room.citizen_word}\n"
                f"🏆 【白板】{user_name} 获胜！\n\n全员身份公示：\n{player_list_str}"
            )
            game_room.status = "ended"
        else:
            await self._send_to_group(game_room,
                f"❌ {user_name} 猜词失败！正确答案是：{game_room.citizen_word}\n游戏继续。"
            )
            yield_result = self._do_next_round(game_room)
            if yield_result:
                yield yield_result

    # ── 胜负判定 ─────────────────────────────────────────────

    def _check_winner(self, game_room: GameRoom) -> str | None:
        """检查游戏是否结束，返回获胜方或 None"""
        alive_players = [p for p in game_room.players if p.is_alive]
        alive_whiteboards = [p for p in alive_players if p.role == "whiteboard"]
        alive_good = [p for p in alive_players if p.role in ("citizen", "whiteboard")]
        alive_undercovers = [p for p in alive_players if p.role == "undercover"]

        # 特殊模式
        if game_room.special_mode:
            # 卧底存活且卧底 >= 白板 → 卧底胜
            if len(alive_undercovers) > 0 and len(alive_undercovers) >= len(alive_whiteboards):
                return "卧底"
            # 卧底被淘汰但不会在此处判定（在 _process_vote_result 中触发猜词）
            return None

        # 普通模式
        if len(alive_undercovers) == 0 and len(alive_whiteboards) == 0:
            return "平民"
        elif len(alive_undercovers) >= len(alive_good):
            return "卧底"
        return None

    # ── 房间管理命令 ─────────────────────────────────────────

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

        for player in game_room.players:
            if player.user_id in self.user_rooms:
                del self.user_rooms[player.user_id]

        del self.game_rooms[room_id]
        yield event.plain_result("游戏已结束，房间已解散")

    @uc.command("add")
    async def add_word_pair(self, event: AstrMessageEvent):
        """添加词语到词库（支持多词）"""
        raw_msg = event.get_message_str()
        m = re.match(r'\S+\s+add\s+(.+)', raw_msg, re.IGNORECASE)
        if not m:
            yield event.plain_result("请输入词语，格式：/uc add <词语1> <词语2> [词语3] ...\n至少需要2个词语")
            return

        words_str = m.group(1).strip()
        words = words_str.split()
        if len(words) < 2:
            yield event.plain_result("至少需要2个词语，格式：/uc add <词语1> <词语2> [词语3] ...")
            return

        # 默认添加到"综合"类别
        categories = self.word_pairs.get("categories", {})
        if "综合" not in categories:
            categories["综合"] = []

        # 检查是否已存在（完全匹配）
        sorted_new = sorted(words)
        for existing_group in categories["综合"]:
            if sorted(existing_group) == sorted_new:
                yield event.plain_result("该词组已存在")
                return

        categories["综合"].append(words)
        self.save_word_pairs(self.word_pairs)
        yield event.plain_result(f"✅ 词语添加成功：{' / '.join(words)}（已加入「综合」类别）")

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
            if game_room.special_mode:
                yield event.plain_result(
                    "你是【白板】，没有词语！请根据其他人的描述推测词语。\n"
                    "你可以随时使用 /uc guess <词语> 猜词，猜对即可获胜！"
                )
            else:
                yield event.plain_result(
                    "你是【白板】，没有词语！请根据其他人的描述推测词语。\n"
                    "如果被票出局，你将获得一次猜词机会。"
                )
        else:
            yield event.plain_result(f"你的词语是：{player.word}\n(请确保你在私聊中查看此消息)")

    async def terminate(self):
        """插件销毁时调用"""
        logger.info("谁是卧底插件已卸载")
