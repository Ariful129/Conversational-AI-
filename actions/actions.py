from typing import Any, Text, Dict, List
import random
import httpx
from datetime import datetime
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

# Service URLs
STORY_SERVICE_URL = "http://localhost:5001"
INTERACTION_SERVICE_URL = "http://localhost:5000"


class ActionRememberChild(Action):
    """Remember child's name and preferences"""

    def name(self) -> Text:
        return "action_remember_child"

    async def run(self, dispatcher: CollectingDispatcher,
                  tracker: Tracker,
                  domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        child_name = next(tracker.get_latest_entity_values("child_name"), None)

        # fallback parsing
        if not child_name:
            text = tracker.latest_message.get("text", "")
            for prefix in ["I'm ", "I’m "]:
                if prefix in text:
                    child_name = text.split(prefix)[-1].strip().split()[0]
                    break

        session_id = tracker.sender_id
        user_id = tracker.sender_id

        if child_name:
            dispatcher.utter_message(text=f"What a beautiful name, {child_name}! Grandma is so happy to meet you, dear!")
            dispatcher.utter_message(text=f"What kind of story would you like to hear today, {child_name}? "
                                          "I know wonderful tales about adventures, magical fairy tales, friendly animals, or exciting space journeys!")
            await self._log_user_event(session_id, user_id, "name_introduction", {"child_name": child_name})
            return [SlotSet("child_name", child_name)]

        return []

    async def _log_user_event(self, session_id, user_id, event_type, event_data):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{INTERACTION_SERVICE_URL}/api/v1/events",
                                  json={"session_id": session_id,
                                        "user_id": user_id,
                                        "event_type": event_type,
                                        "event_data": event_data,
                                        "timestamp": datetime.now().isoformat()})
        except Exception as e:
            print(f"Failed to log user event: {e}")


class ActionTellStory(Action):
    """Main story telling action - gets story from Story Service"""

    def name(self) -> Text:
        return "action_tell_story"

    async def run(self, dispatcher: CollectingDispatcher,
                  tracker: Tracker,
                  domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        child_name = tracker.get_slot("child_name") or "little one"
        story_type = tracker.get_slot("story_type") or "adventure"
        user_id = tracker.sender_id
        session_id = tracker.sender_id

        story_data = await self._get_story_from_service()

        if story_data:
            content = story_data.get("content", {})
            start_node_id = content.get("start_node_id")
            nodes = content.get("nodes", {})

            if start_node_id and start_node_id in nodes:
                narrative_list = nodes[start_node_id].get("narrative", [])
                story_beginning = " ".join(narrative_list).replace("{hero}", child_name)
            else:
                story_beginning = f"Once upon a time, a grand adventure began for {child_name}..."

            story_id = story_data.get("metadata", {}).get("story_id")

            dispatcher.utter_message(text=f"✨ {story_beginning}")
            dispatcher.utter_message(text="What do you think happens next, sweetheart?")

            await self._log_story_event(session_id, user_id, "story_start",
                                        {"story_id": story_id, "story_type": story_type, "child_name": child_name})

            return [SlotSet("current_story_id", story_id),
                    SlotSet("current_story_type", story_type),
                    SlotSet("story_progress", "beginning"),
                    SlotSet("last_node_id", start_node_id)]

        return await self._fallback_template_story(dispatcher, child_name, story_type, session_id, user_id)

    async def _get_story_from_service(self):
        try:
            story_id = "abc12345-6789-4def-9012-3456789abcde"
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{STORY_SERVICE_URL}/api/v1/stories/{story_id}")
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"Failed to get story from service: {e}")
        return None

    async def _log_story_event(self, session_id, user_id, event_type, event_data):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{INTERACTION_SERVICE_URL}/api/v1/events",
                                  json={"session_id": session_id,
                                        "user_id": user_id,
                                        "event_type": event_type,
                                        "event_data": event_data,
                                        "timestamp": datetime.now().isoformat()})
        except Exception as e:
            print(f"Failed to log story event: {e}")

    async def _fallback_template_story(self, dispatcher, child_name, story_type, session_id, user_id):
        templates = {
            "adventure": f"Once upon a time, there was a brave little explorer named {child_name}...",
            "fairy_tale": f"In a kingdom far away, there lived a kind young {child_name}...",
            "animal": f"Deep in the woods lived {child_name}, a clever little fox...",
            "space": f"Captain {child_name} was the youngest astronaut..."
        }
        story_text = templates.get(story_type, templates["adventure"])
        dispatcher.utter_message(text=f"✨ {story_text}")
        dispatcher.utter_message(text="What do you think happens next, sweetheart?")
        await self._log_story_event(session_id, user_id, "story_start_template",
                                    {"story_type": story_type, "child_name": child_name, "template_used": True})
        return [SlotSet("current_story_type", story_type), SlotSet("story_progress", "beginning")]


class ActionContinueStory(Action):
    """Continue story using Story Service nodes or templates"""

    def name(self) -> Text:
        return "action_continue_story"

    async def run(self, dispatcher: CollectingDispatcher,
                  tracker: Tracker,
                  domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        child_name = tracker.get_slot("child_name") or "little one"
        story_id = tracker.get_slot("current_story_id")
        story_progress = tracker.get_slot("story_progress") or "beginning"
        session_id = tracker.sender_id
        user_id = tracker.sender_id

        hero_name = child_name if child_name != "little one" else "the hero"

        if story_id:
            continuation = await self._get_story_continuation_from_service(story_id, story_progress)
            if continuation:
                dispatcher.utter_message(text=f"✨ {continuation}")
                next_progress = self._get_next_progress(story_progress)
                if next_progress != "complete":
                    dispatcher.utter_message(text=f"What do you think {hero_name} should do next?")
                    return [SlotSet("story_progress", next_progress)]
                else:
                    dispatcher.utter_message(text=f"And that's how {hero_name} saved the day! What did you think of that story?")
                    return [SlotSet("story_progress", "complete")]

        # fallback template
        return await self._template_story_continuation(dispatcher, hero_name, "adventure", story_progress, session_id, user_id)

    async def _get_story_continuation_from_service(self, story_id, progress):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{STORY_SERVICE_URL}/api/v1/stories/{story_id}/nodes")
                if response.status_code == 200:
                    nodes = response.json()
                    progress_map = {"beginning": "middle", "middle": "end", "end": "conclusion"}
                    suitable_nodes = [n for n in nodes if n.get("type") == progress_map.get(progress)]
                    if suitable_nodes:
                        node = random.choice(suitable_nodes)
                        return node.get("content", "")
        except Exception as e:
            print(f"Failed to get story continuation: {e}")
        return None

    async def _template_story_continuation(self, dispatcher, hero_name, story_type, progress, session_id, user_id):
        continuations = {
            "adventure": {
                "beginning": f"As {hero_name} sailed across the ocean, they met a friendly dolphin.",
                "middle": f"On the mysterious island, {hero_name} found a cave with glowing crystals.",
                "end": f"The treasure wasn't gold or jewels, but a seed of happiness!"
            }
        }
        story_text = continuations.get(story_type, continuations["adventure"]).get(progress, "And they lived happily ever after!")
        dispatcher.utter_message(text=f"✨ {story_text}")
        next_progress = self._get_next_progress(progress)
        if next_progress != "complete":
            dispatcher.utter_message(text=f"What do you think {hero_name} should do next?")
            return [SlotSet("story_progress", next_progress)]
        else:
            dispatcher.utter_message(text=f"And that's how {hero_name} saved the day!")
            return [SlotSet("story_progress", "complete")]

    def _get_next_progress(self, current_progress):
        return {"beginning": "middle", "middle": "end", "end": "complete"}.get(current_progress, "complete")


class ActionAdaptToEmotion(Action):
    """Adapt story based on child's emotional state"""

    def name(self) -> Text:
        return "action_adapt_to_emotion"

    async def run(self, dispatcher, tracker, domain):
        emotion = tracker.get_slot("current_emotion")
        child_name = tracker.get_slot("child_name") or "sweetheart"
        session_id = tracker.sender_id
        user_id = tracker.sender_id

        if not emotion:
            latest_entities = tracker.latest_message.get("entities", [])
            for entity in latest_entities:
                if entity.get("entity") == "emotion":
                    emotion = entity.get("value")
                    break

        emotion_responses = {
            "scared": f"Oh my dear {child_name}, don't be scared! Grandma will make sure our story has a happy ending.",
            "excited": f"I can see how excited you are, {child_name}! Your enthusiasm makes Grandma happy!",
            "sad": f"Oh sweetie, let's add something wonderful to our story to cheer you up!",
            "curious": f"What a curious mind you have, {child_name}! Let's explore more mysteries!",
            "happy": f"I love seeing you happy, {child_name}! Your joy makes the story more magical!"
        }

        response = emotion_responses.get(emotion, f"I see you're feeling special, {child_name}. Let's make the story reflect that!")
        dispatcher.utter_message(text=response)
        return [SlotSet("current_emotion", emotion)]


class ActionDefaultFallback(Action):
    """Enhanced fallback with logging"""

    def name(self) -> Text:
        return "action_default_fallback"

    async def run(self, dispatcher, tracker, domain):
        child_name = tracker.get_slot("child_name") or "sweetheart"
        user_message = tracker.latest_message.get("text", "")
        session_id = tracker.sender_id
        user_id = tracker.sender_id

        fallback_messages = [
            f"Oh {child_name}, Grandma didn't quite understand that. Could you say it differently?",
            f"I'm sorry dear, could you tell Grandma what you mean in another way?",
            f"Grandma's ears aren't as good as they used to be, {child_name}. Could you repeat that?"
        ]

        message = random.choice(fallback_messages)
        dispatcher.utter_message(text=message)
        return []
