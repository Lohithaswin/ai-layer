from src.intent_router import route_role_intent

tests = [
    "What attributes does the swp-PPC View Full Configuration role have",
    "What attributes does swp-Special test mode have",
    "list all attributes of swp-cop-ps-cluster-admin",
    "which roles have ManageCommands",
    "what is the TDI Values Multiple Turbines Write attribute",
    "what attributes does av tech have",
]

for q in tests:
    result = route_role_intent(q)
    intent = result["intent"]
    entity = result["entity"]
    print(f"Q: {q}")
    print(f"   intent={intent}  entity={entity}")
    print()
