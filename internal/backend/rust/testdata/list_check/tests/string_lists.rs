//! Verify generated variable-length string lists and element constraints.

use cueflow_list_check::messages;

#[test]
fn variable_length_string_lists_are_typed() {
    let empty: messages::Query = serde_json::from_value(serde_json::json!({"tags": []})).unwrap();
    empty.validate().unwrap();
    assert_eq!(empty.tags, Some(Vec::new()));
    assert!(empty.notes.is_none());

    let populated: messages::Query = serde_json::from_value(serde_json::json!({
        "tags": ["alpha", "beta"], "notes": []
    }))
    .unwrap();
    populated.validate().unwrap();
    assert_eq!(
        populated.tags,
        Some(vec!["alpha".to_owned(), "beta".to_owned()])
    );
    assert_eq!(populated.notes, Some(Vec::new()));
}

#[test]
fn list_elements_obey_cue_constraints() {
    for values in [vec![""], vec!["HasUpper"], vec!["has-dash"]] {
        let message = messages::Query {
            tags: Some(values.iter().map(|value| (*value).to_owned()).collect()),
            notes: None,
        };
        assert!(message.validate().is_err());
    }
}

#[test]
fn list_items_must_be_strings() {
    assert!(serde_json::from_value::<messages::Query>(serde_json::json!({"tags": [1]})).is_err());
}
