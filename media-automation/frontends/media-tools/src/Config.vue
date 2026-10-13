<script setup>
import Page from './Page.vue'
defineProps({api:Object,pluginId:{type:String,default:__PLUGIN_ID__}})
</script>
<template><Page :api="api" :plugin-id="pluginId" settings-only /></template>
