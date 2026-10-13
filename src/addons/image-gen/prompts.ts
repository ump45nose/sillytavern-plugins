import { dedupePromptTags } from './vendor/qig/prompt-pipeline.js';
export const defaultTemplate = '将下面的剧情场景转写为用于生图的提示词，只描述能看见的人物、服装、动作、构图、光线与背景。不要写思考、解释或剧情。返回 JSON：{"positive":"…","negative":"…"}。{{style}}\n\n场景：\n{{scene}}';
export function withoutThoughts(text: string) { return text.replace(/<(think|thinking|reasoning|analysis)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '').replace(/<(think|thinking|reasoning|analysis)\b[^>]*>[\s\S]*$/gi, '').replace(/<wb_image_task\b[^>]*>[\s\S]*?<\/wb_image_task>/gi, ''); }
export function cleanPrompts(text: string, style = 'natural'): {
    positive: string;
    negative: string;
} {
    let value = withoutThoughts(text).trim().replace(/^```(?:json|text|markdown)?\s*\n?/i, '').replace(/\n?```\s*$/, '').trim();
    let positive = '', negative = '';
    try {
        const json = JSON.parse(value);
        positive = String(json.positive || json.prompt || json.positive_prompt || '');
        negative = String(json.negative || json.negative_prompt || '');
    }
    catch {
        const xml = value.match(/<(?:positive|prompt)\b[^>]*>([\s\S]*?)<\/(?:positive|prompt)>/i);
        if (xml) {
            positive = xml[1];
            negative = value.match(/<negative\b[^>]*>([\s\S]*?)<\/negative>/i)?.[1] || '';
        }
        else {
            value = value.replace(/^\s*(?:here (?:is|are)|以下(?:是|为)|这是|提示词如下)[^\n]*\n/i, '');
            const split = value.split(/(?:^|\n)\s*(?:negative(?: prompt)?|负面(?:提示词)?)\s*[:：]\s*/i);
            positive = split[0].replace(/^\s*(?:positive(?: prompt)?|prompt|正面(?:提示词)?|提示词)\s*[:：]\s*/i, '');
            negative = split[1] || '';
        }
    }
    const clean = (v: string) => withoutThoughts(v).replace(/<[^>]*>/g, '').replace(/```/g, '').replace(/^\s*["']|["']\s*$/g, '').trim();
    positive = clean(positive);
    negative = clean(negative);
    if (!positive || positive.length < 3 || positive.length > 12000 || /^(?:here (?:is|are)|以下是|抱歉|sorry|i (?:cannot|can't))\b/i.test(positive))
        throw new Error('转写没有得到有效的生图提示词，请编辑后重试。');
    if (style === 'tags') {
        positive = dedupePromptTags(positive);
        negative = dedupePromptTags(negative);
    }
    return { positive, negative };
}
export function sceneSource(messages: {
    id: number;
    role: string;
    text: string;
}[], id: number, before: number) { return messages.filter(m => m.id <= id && m.id >= id - before && m.role !== 'system').map(m => withoutThoughts(m.text).replace(/<[^>]+>/g, '').trim()).filter(Boolean).join('\n\n').slice(-24000); }
