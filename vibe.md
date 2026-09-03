# vibe



现在 strava 的 api client，已经无法免费使用了。



我现在的计划是这样的，把 strava 里面记录过的数据，从 strava 的官网上下载下来，并且记录 strava 上面的最后一天的时间。这是 strava 上面记录的历史数据：/Users/wanshuo/Downloads/export_71335350



然后 strava 数据后，接下来的时间，都从 garmin 去拉取（我的跑步数据都会通过佳明手表去记录，同步到佳明的服务器）。



从佳明拉取数据的实现，在这个仓库里面：/Users/wanshuo/code/my-projects/garmin-health



最后我要实现的效果，就是在 strava api client 失效的情况下，仍然能够每天去同步，去生成。数据来源，有三个：以前手工整理的 + strava 导出的 + garmin 每天动态拉取。



