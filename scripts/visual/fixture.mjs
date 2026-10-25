// Deterministic synthetic content for visual baselines. Original text written for this project.
import { mockApi } from "../browser.mjs";

const think = (text) => `<think>${text}</think>\n`;

export const fixture = {
  mockApi,
  characters: [
    {
      name: "林间",
      avatar: "r-character.webp",
      tags: ["雾港", "长篇"],
      fav: true,
      description: "雾港旧书店的店主，擅长修补受潮的旧信。说话轻，记性极好。",
      personality: "安静、敏锐、偶尔固执。",
      scenario: "雨季末尾的雾港，一封迟到七年的信。",
      first_mes: "雨是在傍晚停的。",
    },
    {
      name: "白芷",
      avatar: "r-user-character.webp",
      tags: ["樱花小径", "RP"],
      fav: false,
      description: "樱花小径上的旧友，总在同一棵树下读书。",
      first_mes: "*她合上书页，抬头看你。* “你来了。”",
    },
    {
      name: "测试角色 · 无头像",
      tags: ["测试"],
      fav: false,
      description: "用于检查无头像时的占位样式。",
      first_mes: "你好。",
    },
  ],
  worlds: [
    {
      name: "雾港志",
      enabled: true,
      entries: [
        {
          key: ["灯塔"],
          comment: "灯塔",
          content: "雾港北岬的灯塔已经熄灭七年，守塔人下落不明。",
          order: 100,
        },
        {
          key: ["旧书店", "书店"],
          comment: "旧书店",
          content: "临街的木门上挂着铜铃，推门时只响半声。",
          order: 90,
        },
        {
          key: [],
          comment: "雾港 · 码头区",
          content: "码头区终年有雾，船只靠钟声辨认航道。",
          constant: true,
          order: 80,
        },
        { key: ["雨季"], comment: "雨季", content: "雨季从五月持续到秋末。", disable: true, order: 70 },
        {
          key: ["渡船"],
          comment: "未寄出的船票",
          content: "抽屉深处夹着一张没有用过的渡船票。",
          vectorized: true,
          order: 60,
        },
        {
          key: ["钟声", "钟"],
          comment: "钟楼",
          content: "码头钟楼每天整点敲三下，雾大时改为五下。",
          order: 50,
        },
      ],
    },
    {
      name: "人物关系",
      enabled: false,
      entries: [
        { key: ["林间"], comment: "林间", content: "林间与守塔人是远亲。", order: 100 },
        { key: ["沈砚"], comment: "沈砚", content: "沈砚七年前离开雾港，此后音讯全无。", order: 90 },
        {
          key: [],
          comment: "称呼约定",
          content: "林间称呼用户为“你”，不用敬称。",
          constant: true,
          order: 80,
        },
      ],
    },
  ],
  personas: [
    {
      name: "作者视角",
      file: "wb-visual-author.png",
      title: "旁白 · 第三人称",
      description: "以作者视角叙述，保持克制的第三人称。",
    },
    {
      name: "沈砚",
      file: "wb-visual-shen.png",
      title: "归乡者",
      description: "七年后回到雾港的人，带着一封没有拆开的信。",
    },
  ],
  presets: [{ name: "长篇 · 细腻", values: { temperature: 0.9, openai_max_tokens: 1200 } }],
  profiles: [
    {
      id: "wb-visual-claude-daily",
      name: "Claude · 日常",
      group: "Claude",
      data: { model: "workbench-fixture" },
    },
    {
      id: "wb-visual-claude-long",
      name: "Claude · 长文",
      group: "Claude",
      data: { model: "workbench-fixture" },
    },
    { id: "wb-visual-local", name: "本地 · 草稿", group: "本地模型", data: { model: "workbench-fixture" } },
  ],
  chat: {
    character: "林间",
    user: "沈砚",
    file: "雾港来信",
    created: "2026-10-01@20h00m00s",
    scene: { day: "12", location: "雾港 · 旧书店", weather: "雨后 · 起雾", time: "18:40" },
    dates: [
      "2026-10-01T12:00:00.000Z",
      "2026-10-01T12:02:00.000Z",
      "2026-10-01T12:05:00.000Z",
      "2026-10-01T12:09:00.000Z",
    ],
    messages: [
      {
        text: "雨是在傍晚停的。\n\n林间推开书店的门时，铜铃只响了半声。屋檐还在滴水，积水里倒映着刚亮起的路灯。",
      },
      { user: true, text: "我站在门口，把伞收起来。“还开着吗？”" },
      {
        text:
          think("用户刚到，先让林间认出对方，但不要立刻点破。") +
          "<content>林间从柜台后抬起头。她手里压着一封被雨水泡软的信，指尖停在信封的折角上。\n\n“开着。”她说，“只是不卖书了，修信。”</content>",
      },
      { user: true, text: "“修信？”我走近柜台，看见那个信封上的字迹，忽然停住。" },
      {
        text: "<content>她没有抬头，只把信封往你这边推了半寸。\n\n“七年前寄出的，”她说，“昨天才到。收件人写的是这家店，可这家店那时候还不是我的。”\n\n窗外的钟楼敲了五下。雾又起来了。</content>",
      },
      { user: true, text: "我认得那是谁的字。我没有伸手。" },
      {
        text:
          think("保持节奏，加入环境描写，给用户留出回应空间。") +
          "<content>林间等了一会儿，见你不动，便把信收回去，夹进一本厚书里。\n\n“不急，”她说，“信已经等了七年，不差这一晚。”\n\n她起身去关窗。雾从码头那边漫过来，把路灯的光晕成一团一团的黄。屋里很安静，只有挂钟在走。\n\n“你要是愿意，可以坐一会儿。我刚煮了茶。”</content>",
      },
      { user: true, text: "“好。”我在靠窗的位置坐下。" },
      {
        text: "<content>茶是旧茶，泡得很淡。林间把杯子放在你面前，自己在对面坐下，膝盖上摊着那本夹了信的书。\n\n“你知道灯塔的事吗？”她忽然问。\n\n“北岬那座。已经灭了七年。”她顿了顿，“和这封信寄出的时间一样。”</content>",
      },
      { user: true, text: "我握着茶杯，热气模糊了眼镜。“你想说什么？”" },
      {
        text: "<content>“我什么也不想说。”林间合上书，“我只是修信的人。信里写了什么，要你自己读。”\n\n她把书推到桌子中间，正好在你们两人之间。\n\n钟楼又敲了五下。雾已经大到看不见对面的街。</content>",
      },
      {
        user: true,
        text: "我把书拉过来，翻到夹信的那一页。信封的封口还没拆，边缘被水泡得起了毛。我犹豫了很久，终于把它拆开。",
      },
    ],
  },
};
