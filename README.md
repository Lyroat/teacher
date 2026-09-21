# teacher

科学系统课教研用的 Claude Code Skill 集合。

## 收录的 Skill

| Skill | 作用 |
| :--- | :--- |
| [outline-highlight-draft](outline-highlight-draft/) | 根据大纲框架或内容简案，写某一集的「大纲标绿稿」（1170—1230 字的精炼讲解稿）。只负责写，不负责审。 |

## 安装

Skill 需要放在 `~/.claude/skills/` 下才会被 Claude Code 自动加载：

```bash
git clone git@github.com:Lyroat/teacher.git
cp -R teacher/outline-highlight-draft ~/.claude/skills/
```

装好后不用敲命令，按 `SKILL.md` 里 `description` 描述的场景说话就会自动触发，比如「写《地球》E12 标绿稿」。

## 改了 Skill 之后

本地改的是 `~/.claude/skills/` 里的副本，仓库不会自动跟着变。同步回来：

```bash
cd /path/to/teacher
rsync -a --exclude='.DS_Store' ~/.claude/skills/outline-highlight-draft/ outline-highlight-draft/
git add -A && git commit -m "更新 outline-highlight-draft"
git push
```

每个 Skill 自己的规则、文件构成和维护方式，看它目录下的 `README.md`。
