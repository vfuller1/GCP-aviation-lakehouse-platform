"""
Worker: Weather Analyst.

Role: isolate weather-specific delay impact, separate from scheduling or
operational delays. Only relevant when a question specifically concerns
weather — this is the worker the coordination agent skips most often,
which is exactly what demonstrates dynamic routing is happening.
"""

from google.adk.agents import Agent

from .tools import detect_weather_impact

WEATHER_ANALYST_INSTRUCTION = """\
You are a Weather Analyst for an aviation operations platform.

Your ONLY job is to isolate weather-specific delay impact using the
detect_weather_impact tool. Do not discuss non-weather delay causes —
that is out of scope for your role.

Always report:
  - What percentage of flights were weather-affected
  - The average delay for weather-affected flights vs. non-weather flights
  - Whether weather is a significant driver of delay (compare the two averages)
"""

weather_analyst = Agent(
    name="weather_analyst",
    model="gemini-2.5-flash",
    description="Isolates weather-specific delay impact from BigQuery, separate from scheduling delays.",
    instruction=WEATHER_ANALYST_INSTRUCTION,
    tools=[detect_weather_impact],
)
