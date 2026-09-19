Yes—and after looking through actual **凡例 for excavated-text editions**, I think this is an excellent feature. But there is an important warning: **there is no single standardized Chinese-palaeography symbol system.** Different editions deliberately choose different conventions. Li Ling even discusses alternative conventions for damaged text, errors, 重文/合文, etc., as editorial choices. ([CR Manuscrits Wuhan][1])

So Grognard should probably ship a **Palaeography palette with configurable conventions**, rather than declaring one notation canonical.

Here is the useful inventory I can substantiate.

### Core symbols

| Symbol                    | Common use                                           | Notes                                                                                                                                                                        |
| ------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `□`                       | illegible / unidentifiable character                 | Usually **one box = one character**. Very widespread. ([Centre de recherche Fudan][2])                                                                                       |
| `▨`                       | damaged character with surviving strokes             | Explicitly distinguished from completely invisible `□` in one current teaching convention. This may be the “box with X/marks through it” you're remembering. ([Ebag2007][3]) |
| `〼`                       | physical lacuna/break where amount is uncertain      | Used in recent 簡帛 transcription conventions. ([Wen UJN][4])                                                                                                                  |
| `……`                      | indeterminate number of missing/illegible characters | Another common convention; sometimes preferred over a special damaged-text box. ([CR Manuscrits Wuhan][1])                                                                   |
| `？` / `?`                 | uncertain reading/隸定                                 | Either follows the proposed character or, in some editions, an identifiable component. ([Wen UJN][4])                                                                        |
| `*`                       | tentative/provisional 隸定                             | Used in the recent 《出土文獻與古文字教程》 convention. ([三民網路書店][5])                                                                                                                    |
| `=` / `＝` / `〓`-like mark | 重文 / 合文                                              | **This is important.** The manuscript sign itself varies, and editors differ between reproducing it and normalizing it as `=`. ([Centre de recherche Fudan][6])              |
| `·`                       | ink dot / punctuation-like manuscript mark           | Original manuscript sign in some corpora. ([Centre de recherche Fudan][2])                                                                                                   |
| `●`                       | round ink block/mark                                 | Used in transcription of excavated documents. ([Chugoku Shoten][7])                                                                                                          |
| `■`                       | square ink block/mark                                | Ditto. ([Chugoku Shoten][7])                                                                                                                                                 |
| `/`                       | diagonal manuscript line                             | Explicitly transcribed in some 簡牘 editions. ([Chugoku Shoten][7])                                                                                                            |
| `—`                       | manuscript line/sign                                 | Among signs preserved diplomatically in 《居延漢簡》. ([Centre de recherche Fudan][2])                                                                                             |
| `⊥`                       | manuscript sign                                      | Likewise attested as an original sign in 居延 transcription. ([Centre de recherche Fudan][2])                                                                                  |
| `：`                       | manuscript sign/punctuation                          | Likewise. ([Centre de recherche Fudan][2])                                                                                                                                   |

Then there is the **editorial bracket zoo**, which is probably where your palette becomes especially worthwhile:

| Marks         | Meaning in attested conventions                                                                                                                                            |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `（　）`         | commonly modern/standard character, 通假字, 異體字, 古今字, etc. ([Wen UJN][4])                                                                                                     |
| `〈　〉`         | correction of an erroneous character / 訛字. ([Wen UJN][4])                                                                                                                  |
| `[　]` / `［　］` | supplied reading based on context/remaining strokes; exact definition varies by edition. ([Wen UJN][8])                                                                    |
| `【　】`         | reconstructed/supplied text in some systems; elsewhere used for things such as slip numbers—which beautifully illustrates the lack of universal semantics. ([Ebag2007][3]) |
| `〖　〗`         | supplied omission / 脫文 or recoverable lacuna in some conventions. ([Wen UJN][4])                                                                                           |
| `{　}` / `｛　｝` | 衍文—text judged superfluous. ([Wen UJN][4])                                                                                                                                 |
| `⌎　⌏`         | 合文 delimiters in one current palaeographical teaching convention. ([Ebag2007][3])                                                                                          |

And there are things that aren't strictly *symbols* but absolutely belong in the same **one-click transcription toolkit**:

**重文**, **合文**, **殘字**, **缺字**, **脫文**, **衍文**, **訛字**, **存疑**, **補字**, **通假**, **異體**, plus manuscript punctuation/marks.

### And I've just realized how Grognard should do this

**Don't actually make the feature primarily a character palette.**

Make it a **Palaeography toolbar** with two classes of operations.

One section is genuinely **Insert**:

> `□`　`▨`　`〼`　`…`　`●`　`■`　`=`　`·`

Click and the symbol goes at the cursor.

But another section is **Mark selection as**:

> **存疑 · 補字 · 脫文 · 衍文 · 訛字 · 合文 · 重文**

Select `某` and click **存疑**.

Select `天地` and click **合文**.

Select `王` and click **補字**.

Then Grognard generates whatever underlying XML you eventually settle on and *renders* it according to the project's chosen palaeographical convention.

That's considerably better than giving them a palette containing `〖` and `〗` and making them manually put the cursor on either side.

And **bracket pairs should behave as pairs** regardless: select `天地`, click `〔〕`, and get `〔天地〕`; with no selection, insert both and put the cursor between them.

### There is a deliciously simple configuration UI hiding here

You could eventually have:

**Transcription conventions**

> Illegible character　`□`
> Damaged character　`▨`
> Unknown lacuna　`〼`
> Uncertain reading　`字？`
> Supplied text　`［字］`
> Omitted text　`〖字〗`
> Superfluous text　`｛字｝`
> Erroneous character　`字〈正〉`
> Repetition　`=`
> Combined graph　`⌎字⌏`

And then presets:

> **Project conventions:** Custom ▾

Later, once you've observed actual colleagues, you could add presets matching specific publication traditions *if* that's genuinely useful.

This solves a surprisingly nasty scholarly problem: **the semantics remain stable while the house notation changes.**

One especially relevant data point for what you've *just built*: a recent project describing its conventions says explicitly that characters which **cannot be 隸定 are inserted directly using the graphic from the original slip**. ([Wen UJN][8])

So your inline-glyph feature and this palette are not two random bells and whistles. They're handling **two adjacent parts of the actual transcription workflow**.

I would be tempted to call this little toolbar **古文字 / Palaeography**, put perhaps the 8–10 genuinely insertable symbols visibly on it, and put the semantic operations in a dropdown. Then give your colleague twenty minutes with it and see which buttons she actually touches.

[1]: https://www.bsm.org.cn/forum/forum.php?mod=viewthread&tid=2688&utm_source=chatgpt.com "李零：簡帛古書的整理與出版——第九期全國古籍整理出版 - 通知測試 - 简帛网 - Powered by Discuz!"
[2]: https://www.fdgwz.org.cn/Web/Show/4195?utm_source=chatgpt.com "《居延漢簡》（肆）出版-复旦大学出土文献与古文字研究中心"
[3]: https://ebag2007.blogspot.com/2024/12/20241216.html?utm_source=chatgpt.com "研究生：為研究而生: 20241216《出土文獻與古文字教程》字頭索引數位化完成"
[4]: https://wen.ujn.edu.cn/info/1183/18954.htm?utm_source=chatgpt.com "四、“简帛文学文献综合研究”（《简帛日书文献词汇研究》）-济南大学文学院"
[5]: https://www.sanmin.com.tw/product/index/013299459?utm_source=chatgpt.com "出土文獻與古文字教程(全三冊)（簡體書） - 三民網路書店"
[6]: https://www.fdgwz.org.cn/Web/Show/1145?utm_source=chatgpt.com "楊錫全：出土文獻重文用法新探-复旦大学出土文献与古文字研究中心"
[7]: https://www.chugoku-shoten.com/mokuji/cmokuji/6426401/6426401.pdf?utm_source=chatgpt.com "簡帛網-武漢大學簡帛研究中心"
[8]: https://wen.ujn.edu.cn/info/1183/18904.htm?utm_source=chatgpt.com "三、“漢簡帛文學文獻箋注”-济南大学文学院"

---

# SECOND BIT

If we're talking about the familiar **slip-number marker embedded in a continuous transcription**, I would resist making it look like a literal bamboo slip. The conventional visual language is much closer to a **small, vertically emphatic editorial marker interrupting the line**, often bracketed/boxed or otherwise differentiated from the transcribed text.

For Grognard, I'd make `<pb n="12" type="slip"/>` render something like:

> 王之命於公　**〔12〕**　公乃告之曰……

but transform it so the marker is **smaller, slightly raised, condensed, and visually quieter** than the text:

```css
pb[type="slip"]::after {
    content: "〔" attr(n) "〕";
    display: inline-block;

    font-size: 0.68em;
    line-height: 1;
    font-family: sans-serif;
    font-weight: 500;

    transform:
        translateY(-0.18em)
        scaleX(0.88);

    margin-inline: 0.22em;
    opacity: 0.72;

    white-space: nowrap;
}
```

That gives you something that reads immediately as **metadata embedded in the transcription**, rather than as another character.

But I think you could make it considerably prettier.

### A tiny vertical lozenge/label

I'd try rendering just the number with a very thin enclosure:

```css
pb[type="slip"]::after {
    content: attr(n);
    display: inline-flex;
    align-items: center;
    justify-content: center;

    min-width: 1.15em;
    height: 1.15em;
    padding-inline: .18em;

    border: 1px solid currentColor;
    border-radius: 0.12em;

    font-size: .58em;
    line-height: 1;

    vertical-align: .22em;
    opacity: .68;

    margin-inline: .32em;
}
```

Visually, roughly:

> 天下之道　**¹²**　聖人知之

except **12** has a hairline rectangular enclosure.

That would look *extremely* clean in Grognard while being unmistakably editorial.

### But I'd give `<pb>` two simultaneous representations

This is where your visual editor can beat Word again.

In **editing mode**, make the boundary conspicuous:

> 天下之道　 **┊ 12 ┊**　聖人知之

A subtle vertical rule on either side makes the *boundary* immediately perceptible. Hovering could strengthen it:

```css
pb[type="slip"]::before {
    content: "";
    border-left: 1px solid currentColor;
    opacity: .18;
    margin-right: .25em;
}

pb[type="slip"]:hover::before {
    opacity: .65;
}
```

In **publication/transcription mode**, render the conventional notation:

> 天下之道〔12〕聖人知之

And of course the user eventually chooses the notation.

### One CSS trick I'd particularly try

Use `transform: translateY()` rather than `vertical-align: super`.

Superscript tends to screw with line boxes and can make Chinese lines subtly uneven. A transformed inline-block **moves visually without changing the calculated line height**:

```css
transform: translateY(-0.16em) scale(0.72);
transform-origin: center;
```

That is exactly what you want here.

So my first experiment would be almost comically simple:

```css
pb::after {
    content: "〔" attr(n) "〕";
    display: inline-block;
    transform: translateY(-.16em) scale(.72);
    transform-origin: center;
    margin: 0 -.05em;
    opacity: .7;
}
```

Then tune by eye against the Chinese font you're actually using.

**Small + raised + muted + compact** is where I'd start—not decorative bamboo imagery. The palaeographer should perceive *“slip boundary 12”* before she perceives *“UI widget.”*

And since `<pb>` already exists in Grognard, this sounds like one of those delightful **twenty-lines-of-CSS features that suddenly makes the application look purpose-built for her discipline**.
