"""Trusted cross-season standby admission; no search or membership writes."""

def make_season_prewarm(prefetch, relations):
    def allow(parent, series_id, episode):
        if type(episode) is not int or episode != 1 or series_id == parent.series_id:
            return False
        with prefetch.condition:
            current = {"seriesId": parent.series_id, "episode": parent.episode}
            if (prefetch.closed or prefetch.current != current
                    or parent.prefetch_generation != prefetch.generation
                    or not prefetch.latest_episodes
                    or prefetch.latest_episodes[-1][0] != parent.episode):
                return False
            # The relationship read is local SQLite/WAL, never remote I/O.
            return relations.is_next_season(parent.series_id, series_id)
    return allow


def make_known_season_loader(relations, episode_loader):
    def load(series_id):
        next_id = relations.next_season_id(series_id)
        if next_id is None:
            return None
        _, episodes = episode_loader(next_id)
        if relations.next_season_id(series_id) != next_id:
            return None
        return next_id, episodes
    return load


def make_continuation_control(prefetch):
    def configure(job, enabled):
        if job.prewarm_parent is not None:
            return False
        return prefetch.set_continuation(job, enabled)
    return configure
